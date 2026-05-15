# Code Samples

Three projects spanning cloud infrastructure, data engineering, and applied ML.

---

## 1. Genomic Annotation Service (Cloud Computing)

**Files:** [`cloud-computing/views.py`](https://github.com/evanfantozzi/code-samples/blob/main/cloud-computing/views.py), [`cloud-computing/annotator.py`](https://github.com/evanfantozzi/code-samples/blob/main/cloud-computing/annotator.py)

A genomic annotation platform built on AWS that I worked on as part of my cloud computing course. Users upload VCF files through a Flask web app, which generates S3 presigned POSTs, so files go directly to S3 without passing through the server. After upload, the app writes a job record to DynamoDB and publishes a job to SNS. A separate annotator service runs on EC2, long-polling an SQS queue, downloading input files from S3, spawning annotation subprocesses per job, and updating job status in DynamoDB with conditional writes to prevent race conditions. Results are served back via presigned GET URLs.

**AWS services used:** S3, SQS, SNS, DynamoDB, EC2

---

## 2. InsightOut (Data Engineering / Django)

**Files:** [`insightout/models.py`](https://github.com/evanfantozzi/code-samples/blob/main/insightout/models.py), [`insightout/add_data.py`](https://github.com/evanfantozzi/code-samples/blob/main/insightout/add_data.py)

InsightOut is an ongoing group project for my applied Civic Technology course. It is a tool designed to help global health organizations predict child health outcomes in low-resource settings using Demographic and Health Survey data. `models.py` defines the full relational schema in Django — geographic hierarchy (countries, admin units, clusters), raw and cleaned survey variables, households and individuals, satellite data, and ML model outputs. `add_data.py` implements the data ingestion pipeline, with functions that upsert DHS survey data from DataFrames into the database using atomic transactions and in-memory caching to minimize redundant queries across large datasets.

**Stack:** Django, GeoDjango, PostgreSQL/PostGIS, pandas

---

## 3. Applied NLP Analysis 

**File:** [`scrubs-analysis/fine_tune.ipynb`](https://github.com/evanfantozzi/code-samples/blob/main/scrubs-analysis/fine_tune.ipynb)

Part of an NLP pipeline to analyze how humor and emotional intensity shape the TV show Scrubs. After scraping episode transcripts and manually labeling a sample of scenes, I fine-tuned DeBERTa to classify scenes by humor and emotional intensity, experimenting with different optimizers (AdamW vs. SGD), dropout configurations, and pooling strategies (CLS token vs. mean pooling).

**Stack:** PyTorch, HuggingFace Transformers, DeBERTa
