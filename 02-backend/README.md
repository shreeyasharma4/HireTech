# Intelligent Resume Screening Backend

FastAPI backend extracted and reconstructed from the uploaded PDF.

## Features

- Accepts multiple resumes in one request.
- Supports PDF, DOCX and TXT resumes.
- Accepts a job description through form data.
- Matches JD skills against each resume.
- Calculates a percentage score.
- Returns matched and missing skills.
- Ranks candidates by score.

## Install

```bash
pip install -r requirements.txt
```

## Run locally

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## API

### Health check

`GET /health`

Expected response:

```json
{"status": "ok"}
```

### Screen resumes

`POST /screen`

Use `multipart/form-data` with:

- `jd`: job description text
- `resumes`: one or more PDF/DOCX/TXT files

Example response:

```json
{
  "results": [
    {
      "rank": 1,
      "candidate": "Candidate Name",
      "score": 80,
      "matched_skills": ["Python", "FastAPI"],
      "missing_skills": ["Docker"]
    }
  ]
}
```
