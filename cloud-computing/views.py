import uuid
import time
import json
from datetime import datetime

import boto3
from botocore.client import Config
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from flask import abort, flash, redirect, render_template, request, session, url_for, jsonify

from app import app, db
from decorators import authenticated, is_premium


def gen_presigned_post(client, bucket_name, key_name, redirect_url):
    """
    Generate a presigned POST request to S3.
    """
    encryption = app.config["AWS_S3_ENCRYPTION"]
    acl = app.config["AWS_S3_ACL"]

    fields = {
        "success_action_redirect": redirect_url,
        "x-amz-server-side-encryption": encryption,
        "acl": acl,
        "csrf_token": app.config["SECRET_KEY"],
    }
    conditions = [
        ["starts-with", "$success_action_redirect", redirect_url],
        {"x-amz-server-side-encryption": encryption},
        {"acl": acl},
        ["starts-with", "$csrf_token", ""],
    ]

    presigned_post = client.generate_presigned_post(
        Bucket=bucket_name,
        Key=key_name,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=app.config["AWS_SIGNED_REQUEST_EXPIRATION"],
    )
    return presigned_post


def gen_presigned_get(client, bucket_name, key_name):
    """
    Generate a presigned GET request to S3.
    """
    try:
        response = client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': key_name},
            ExpiresIn=app.config["AWS_SIGNED_REQUEST_EXPIRATION"],
        )
    except ClientError as e:
        app.logger.error(f"Unable to get object {key_name}: {e}")
        abort(500)

    return response


"""
Start annotation request
Create the required AWS S3 policy document and render a form for
uploading an annotation input file using the policy document
"""


@app.route("/annotate", methods=["GET"])
@authenticated
def annotate():
    s3 = boto3.client(
        "s3",
        region_name=app.config["AWS_REGION_NAME"],
        config=Config(signature_version="s3v4"),
    )

    bucket_name = app.config["AWS_S3_INPUTS_BUCKET"]
    user_id = session["primary_identity"]

    # Generate unique ID to be used as S3 key (name)
    key_name = (
        app.config["AWS_S3_KEY_PREFIX"]
        + user_id
        + "/"
        + str(uuid.uuid4())
        + "~${filename}"
    )

    try:
        presigned_post = gen_presigned_post(
            client=s3,
            bucket_name=bucket_name,
            key_name=key_name,
            redirect_url=str(request.url) + "/job")
    except ClientError as e:
        app.logger.error(f"Unable to generate presigned URL for upload: {e}")
        return abort(500)

    return render_template(
        "annotate.html", s3_post=presigned_post, role=session["role"]
    )


"""
Fires off an annotation job
Accepts the S3 redirect GET request, parses it to extract
required info, saves a job item to the database, and then
publishes a notification for the annotator service.
"""


@authenticated
@app.route("/annotate/job", methods=["GET"])
def create_annotation_job_request():

    region = app.config["AWS_REGION_NAME"]

    try:
        bucket_name = request.args.get("bucket")
        s3_key = request.args.get("key")
    except ClientError as e:
        app.logger.error(f"Unable to parse request arguments: {e}")
        return abort(404)

    try:
        key_without_input_file, input_file_name = s3_key.split("~", 1)
        _, _, job_id = key_without_input_file.split("/")
    except (ValueError, KeyError, AttributeError) as e:
        app.logger.error(f"Unable to parse key {s3_key}: {e}")
        return abort(404)

    try:
        user_id = session["primary_identity"]
    except KeyError as e:
        app.logger.error(f"Unable to get user id: {e}")

    try:
        dynamodb = boto3.resource('dynamodb', region_name=region)
        table = dynamodb.Table(app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"])
        data = {
            "job_id": job_id,
            "user_id": user_id,
            "input_file_name": input_file_name,
            's3_inputs_bucket': bucket_name,
            's3_key_input_file': s3_key,
            'submit_time': int(time.time()),
            'job_status': 'PENDING',
        }
        resp = table.put_item(Item=data)

        status_code = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status_code != 200:
            app.logger.error(f"Unable to update {user_id}'s job status in database for job {job_id}")
            return abort(status_code)

    except ClientError as e:
        app.logger.error(f"Unable to update {user_id}'s job status in database for job {job_id}: {e}")
        return abort(404)

    try:
        client = boto3.client("sns", region_name=region)
        resp = client.publish(
            TopicArn=app.config["AWS_SNS_JOB_REQUEST_TOPIC"],
            Message=json.dumps(data),
        )

        status_code = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status_code != 200:
            app.logger.error(f"Unable to publish job request to SNS for job {job_id}")
            return abort(status_code)

    except ClientError as e:
        app.logger.error(f"Unable to publish job request to SNS for job {job_id}: {e}")
        return abort(500)

    return render_template("annotate_confirm.html", job_id=job_id)


def format_sec_since_epoch(sec_since_epoch):
    """
    Takes in string representation of seconds since epoch and converts it to formatted string.
    """
    if sec_since_epoch:
        request_date_time = datetime.fromtimestamp(int(sec_since_epoch))
        return request_date_time.strftime("%Y-%m-%d @ %H:%M:%S")
    else:
        return None


def confirm_user_access(item_user, session_user):
    """
    Checks whether a user has access to an item, returns True if so, raises 403 otherwise.
    """
    if item_user != session_user:
        app.logger.error(
            f"User {session_user} does not have permission to access this job, belongs to {item_user}"
        )
        return abort(403)
    else:
        return True


"""
List all annotations for the user
"""


@app.route("/annotations", methods=["GET"])
def annotations_list():
    user_id = session["primary_identity"]

    try:
        client = boto3.client(
            "dynamodb",
            region_name=app.config["AWS_REGION_NAME"],
        )
    except ClientError as e:
        app.logger.error(f"Unable to connect to DynamoDB: {e}")
        return abort(500)

    try:
        paginator = client.get_paginator('query')
        pages = paginator.paginate(
            TableName=app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"],
            IndexName=app.config["USER_INDEX"],
            KeyConditionExpression="user_id = :user_id",
            ExpressionAttributeValues={":user_id": {"S": user_id}}
        )

        annotations = []
        for page in pages:
            for item in page.get("Items", []):
                annotations.append({
                    "request_id": item.get("job_id", {}).get("S"),
                    "request_time": format_sec_since_epoch(
                        item.get("submit_time", {}).get("N")
                    ),
                    "vcf_file_name": item.get("input_file_name", {}).get("S"),
                    "status": item.get("job_status", {}).get("S"),
                })

    except ClientError as e:
        app.logger.error(f"Unable to query DynamoDB for user {user_id}'s annotations: {e}")
        return abort(404)

    return render_template("annotations.html", annotations=annotations)


def find_job_in_dynamodb(id):
    """
    Given a job ID, connect to DynamoDB, query the annotations table, and return the item.
    """
    try:
        client = boto3.client(
            "dynamodb",
            region_name=app.config["AWS_REGION_NAME"],
        )
    except ClientError as e:
        app.logger.error(f"Unable to connect to DynamoDB: {e}")
        return abort(500)

    try:
        response = client.query(
            TableName=app.config["AWS_DYNAMODB_ANNOTATIONS_TABLE"],
            KeyConditionExpression='job_id = :job_id',
            ExpressionAttributeValues={
                ':job_id': {'S': id}
            }
        )
    except ClientError as e:
        app.logger.error(f"Unable to query DynamoDB for job {id}: {e}")
        return abort(500)

    jobs = response.get("Items", [])

    if len(jobs) > 1:
        app.logger.error(f"More than one job found for id {id}: {jobs}")
        return abort(404)
    elif not jobs:
        app.logger.error(f"No job found for id {id}")
        return abort(404)
    else:
        return jobs[0]


def generate_s3_client():
    try:
        client = boto3.client(
            "s3",
            region_name=app.config["AWS_REGION_NAME"],
            config=Config(signature_version="s3v4"),
        )
    except ClientError as e:
        app.logger.error(f"Unable to connect to S3: {e}")
        return abort(500)

    return client


"""
Display details of a specific annotation job
"""


@app.route("/annotations/<id>", methods=["GET"])
def annotation_details(id):

    item = find_job_in_dynamodb(id)

    confirm_user_access(
        item_user=item.get("user_id", {}).get("S"),
        session_user=session.get("primary_identity")
    )

    s3_client = generate_s3_client()

    presigned_gets = {}
    for file in ["input", "results"]:

        if file == "results" and item.get("job_status", {}).get("S") != "COMPLETED":
            continue

        try:
            key_name = item["s3_key_input_file"]["S"] if file == "input" else item["s3_key_result_file"]["S"]
        except KeyError as e:
            app.logger.error(f"Unable to extract S3 Key Name: {e}")
            return abort(404)

        presigned_gets[file] = gen_presigned_get(
            client=s3_client,
            bucket_name=app.config["AWS_S3_INPUTS_BUCKET"] if file == "input" else app.config["AWS_S3_RESULTS_BUCKET"],
            key_name=key_name,
        )

    job = {
        "request_id": item.get("job_id", {}).get("S"),
        "vcf_input_file": item.get("input_file_name", {}).get("S"),
        "status": item.get("job_status", {}).get("S"),
        "request_time": format_sec_since_epoch(
            item.get("submit_time", {}).get("N")
        ),
        "complete_time": format_sec_since_epoch(
            item.get("complete_time", {}).get("N")
        ),
        "results_file_archive_id": item.get("results_file_archive_id", {}).get("S"),
        "results_file": presigned_gets.get("results"),
        "input_file": presigned_gets.get("input"),
    }

    return render_template("annotation.html", job=job, id=id)


"""
Display the log file contents for an annotation job
"""


@app.route("/annotations/<id>/log", methods=["GET"])
def annotation_log(id):
    item = find_job_in_dynamodb(id)

    confirm_user_access(
        item_user=item.get("user_id", {}).get("S"),
        session_user=session.get("primary_identity")
    )

    s3_client = generate_s3_client()
    try:
        resp = s3_client.get_object(
            Bucket=app.config["AWS_S3_RESULTS_BUCKET"],
            Key=item["s3_key_log_file"]["S"],
        )
        log = resp["Body"].read().decode("utf-8")

    except (ClientError, KeyError) as e:
        app.logger.error(f"Unable to read job {id} from S3: {e}")
        return abort(404)

    return render_template("view_log.html", log=log, job_id=id)


"""Subscription management handler
"""
import stripe
from auth import update_profile


@app.route("/subscribe", methods=["GET", "POST"])
def subscribe():
    if request.method == "GET":
        pass
    elif request.method == "POST":
        pass


"""DO NOT CHANGE CODE BELOW THIS LINE
*******************************************************************************
"""

"""Set premium_user role
"""


@app.route("/make-me-premium", methods=["GET"])
@authenticated
def make_me_premium():
    update_profile(identity_id=session["primary_identity"], role="premium_user")
    return redirect(url_for("profile"))


"""Reset subscription
"""


@app.route("/unsubscribe", methods=["GET"])
@authenticated
def unsubscribe():
    update_profile(identity_id=session["primary_identity"], role="free_user")
    return redirect(url_for("profile"))


"""Home page
"""


@app.route("/", methods=["GET"])
def home():
    return render_template("home.html"), 200


"""Login page; send user to Globus Auth
"""


@app.route("/login", methods=["GET"])
def login():
    app.logger.info(f"Login attempted from IP {request.remote_addr}")
    if request.args.get("next"):
        session["next"] = request.args.get("next")
    return redirect(url_for("authcallback"))


"""404 error handler
"""


@app.errorhandler(404)
def page_not_found(e):
    return (
        render_template(
            "error.html",
            title="Page not found",
            alert_level="warning",
            message="The page you tried to reach does not exist. \
      Please check the URL and try again.",
        ),
        404,
    )


"""403 error handler
"""


@app.errorhandler(403)
def forbidden(e):
    return (
        render_template(
            "error.html",
            title="Not authorized",
            alert_level="danger",
            message="You are not authorized to access this page. \
      If you think you deserve to be granted access, please contact the \
      supreme leader of the mutating genome revolutionary party.",
        ),
        403,
    )


"""405 error handler
"""


@app.errorhandler(405)
def not_allowed(e):
    return (
        render_template(
            "error.html",
            title="Not allowed",
            alert_level="warning",
            message="You attempted an operation that's not allowed; \
      get your act together, hacker!",
        ),
        405,
    )


"""500 error handler
"""


@app.errorhandler(500)
def internal_error(error):
    return (
        render_template(
            "error.html",
            title="Server error",
            alert_level="danger",
            message="The server encountered an error and could \
      not process your request.",
        ),
        500,
    )


"""CSRF error handler
"""


from flask_wtf.csrf import CSRFError


@app.errorhandler(CSRFError)
def csrf_error(error):
    return (
        render_template(
            "error.html",
            title="CSRF error",
            alert_level="danger",
            message=f"Cross-Site Request Forgery error detected: {error.description}",
        ),
        400,
    )


### EOF
