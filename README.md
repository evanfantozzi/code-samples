# Code Samples

Three projects spanning cloud infrastructure, data engineering, and applied ML.

---

## 1. Genomic Annotation Service (Cloud Computing)

**Files:** [`cloud-computing/views.py`](cloud-computing/views.py), [`cloud-computing/annotator.py`](cloud-computing/annotator.py)

A full-stack genomic annotation platform built on AWS. Users upload VCF files through a Flask web app, which generates S3 presigned POSTs so files go directly to S3 without passing through the server. After upload, the web layer writes a job record to DynamoDB and publishes to SNS. A separate annotator service runs on EC2, long-polling an SQS queue, downloading input files from S3, spawning annotation subprocesses per job, and updating job status in DynamoDB with conditional writes to prevent race conditions. Results are served back via presigned GET URLs.

**Key AWS services:** S3, SQS, SNS, DynamoDB, EC2

---

## 2. InsightOut (Data Engineering / Django)

**Files:** [`insightout/models.py`](insightout/models.py), [`insightout/add_data.py`](insightout/add_data.py)

InsightOut is a research platform designed to help global health organizations predict child health outcomes in low-resource settings using DHS survey data. `models.py` defines the full relational schema in Django — geographic hierarchy (countries, admin units, clusters), raw and cleaned survey variables, households and individuals, satellite data, and ML model outputs. `add_data.py` implements the data ingestion pipeline, with functions that upsert DHS survey data from DataFrames into the database using atomic transactions and in-memory caching to minimize redundant queries across large datasets.

**Stack:** Django, GeoDjango, PostgreSQL/PostGIS, pandas

---

## 3. Scrubs NLP Analysis (Applied ML)

**File:** [`scrubs-analysis/fine_tune.ipynb`](scrubs-analysis/fine_tune.ipynb)

An end-to-end NLP pipeline to analyze how humor and emotional intensity shape audience reactions to the TV show Scrubs. After scraping episode transcripts and manually labeling a sample of scenes, I fine-tuned DeBERTa (via HuggingFace) to classify scenes by humor and emotional intensity, experimenting with different optimizers (AdamW vs. SGD), dropout configurations, and pooling strategies (CLS token vs. mean pooling). I also prompted Gemini 2.5 models as a baseline. Scene-level predictions were aggregated into episode-level features and used to model IMDb ratings, finding that emotional variance accounts for roughly 18% of rating variability.

**Stack:** PyTorch, HuggingFace Transformers, DeBERTa, Gemini API
