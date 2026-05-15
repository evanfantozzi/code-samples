import boto3
import json
import os
import shutil
import sys
from datetime import datetime
import subprocess
from subprocess import Popen, PIPE
from botocore.exceptions import ClientError

from configparser import ConfigParser, ExtendedInterpolation

config = ConfigParser(os.environ, interpolation=ExtendedInterpolation())
config.read("annotator_config.ini")


def run_annotation_job(user_id: str, job_id: str, input_file_name: str):
    """
    Runs the annotation subprocess for a given job. Cleans up the job directory
    and returns False if the subprocess fails to launch.
    """
    job_path = f"{config['gas']['JobPath']}/{job_id}"
    try:
        subprocess.Popen(
            ["python", os.path.abspath(config['ann']['RunPath']), input_file_name, user_id, job_id],
            text=True, cwd=job_path
        )
    except (
            FileNotFoundError,
            PermissionError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
    ) as e:
        shutil.rmtree(job_path)
        print(f"Failed to run annotator job for {job_path}/{input_file_name}: {e}")
        return False

    return True


def update_job_status_to_running(job_id: str):
    """
    Conditionally updates the job status in DynamoDB from PENDING to RUNNING.
    Ignores ConditionalCheckFailedException (job already advanced past PENDING).
    """
    try:
        dynamodb = boto3.resource('dynamodb', region_name=config['aws']['AwsRegionName'])
        table = dynamodb.Table(config['gas']['AnnotationsTable'])
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression='SET job_status = :val1',
            ExpressionAttributeValues={":val1": "RUNNING", ":val2": "PENDING"},
            ConditionExpression='job_status = :val2'
        )
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') != "ConditionalCheckFailedException":
            print(f"Failed to update job {job_id} status to RUNNING: {e}")
            return False

    return True


def request_annotation(job: dict) -> bool:
    """
    Downloads the input file from S3, launches the annotation subprocess,
    and updates the job status to RUNNING in DynamoDB.
    """
    try:
        user_id = job["user_id"]
        job_id = job["job_id"]
        input_file_name = job["input_file_name"]
        s3_key_input_file = job["s3_key_input_file"]
        s3_inputs_bucket = job["s3_inputs_bucket"]
    except KeyError as e:
        print(f"Unable to parse job JSON: {e}")
        return False

    try:
        client = boto3.client("s3", region_name=config['aws']['AwsRegionName'])
        job_path = f"{config['gas']['JobPath']}/{job_id}"
        os.makedirs(job_path, exist_ok=True)
        client.download_file(s3_inputs_bucket, s3_key_input_file, f'{job_path}/{input_file_name}')
    except (ClientError, OSError, PermissionError) as e:
        print(f"Unable to save {s3_key_input_file} to instance: {e}")
        return False

    if run_annotation_job(user_id=user_id, job_id=job_id, input_file_name=input_file_name):
        if update_job_status_to_running(job_id=job_id):
            return True
        else:
            return False
    else:
        return False


def poll_queue(client: boto3.client, queue_url: str):
    """
    Long-polls SQS for up to 10 messages, returning them as a list.
    """
    try:
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=int(config['sqs']['MaxMessages']),
            WaitTimeSeconds=int(config['sqs']['WaitTime'])
        )
    except ClientError as e:
        print(f"Unable to poll queue: {e}")
        return []

    return response.get("Messages", [])


def delete_message(client: boto3.client, queue_url: str, receipt_handle: str):
    """
    Deletes a processed message from SQS.
    """
    try:
        client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle
        )
    except ClientError as e:
        print(f"Unable to delete message {receipt_handle}: {e}")


if __name__ == "__main__":
    client = boto3.client('sqs', region_name=config['aws']['AwsRegionName'])
    queue_url = config['sqs']['QueueUrl']

    while True:
        print(f"Polling at {datetime.now()}...\n")
        messages = poll_queue(client=client, queue_url=queue_url)
        if messages:
            for message in messages:
                try:
                    receipt_handle = message.get("ReceiptHandle")
                    job = json.loads(json.loads(message.get("Body", {})).get("Message", {}))
                except json.decoder.JSONDecodeError as e:
                    print(f"Unable to parse message JSON: {message.get('Body')}: {e}")
                    continue

                successful_job = request_annotation(job)

                if successful_job:
                    delete_message(client=client, queue_url=queue_url, receipt_handle=receipt_handle)
