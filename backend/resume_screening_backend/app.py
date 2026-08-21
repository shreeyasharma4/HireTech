import io
import re
from typing import List, Set

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document as DocxDocument

app = FastAPI(title="Intelligent Resume Screening")

# Frontend can be served from a different origin/port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------
# Text extraction (PDF / DOCX / TXT)
# -----------------------------------------

def extract_text_from_pdf(raw: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(
            (page.extract_text() or "") for page in reader.pages
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF read failed: {e}")


def extract_text_from_docx(raw: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DOCX read failed: {e}")


def extract_text_from_txt(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract_text(filename: str, raw: bytes) -> str:
    name = filename.lower()

    if name.endswith(".pdf"):
        return extract_text_from_pdf(raw)
    if name.endswith(".docx"):
        return extract_text_from_docx(raw)
    if name.endswith(".txt"):
        return extract_text_from_txt(raw)

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type: {filename}",
    )


# -----------------------------------------
# Skill matching
# -----------------------------------------

# JD skills are expected to be comma/newline/semicolon/pipe separated.
_SPLIT_RE = re.compile(r"[,\n;/|]+")
_WORD_RE = re.compile(r"[A-Za-z0-9+.#]+")


def parse_jd_skills(jd_text: str) -> List[str]:
    """Extract candidate skill phrases from comma/newline separated JD text."""
    raw_parts = [p.strip() for p in _SPLIT_RE.split(jd_text) if p.strip()]

    skills = []
    seen = set()

    for part in raw_parts:
        # Remove things such as "2+ years experience" from the skill list.
        if re.search(r"\byears?\b", part, re.I):
            continue

        key = part.lower()
        if key not in seen:
            seen.add(key)
            skills.append(part)

    return skills


def normalize_tokens(text: str) -> Set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def skill_present(
    skill: str,
    resume_text_lower: str,
    resume_tokens: Set[str],
) -> bool:
    skill_lower = skill.lower().strip()

    if not skill_lower:
        return False

    # Multi-word skills such as "Machine Learning" use substring matching.
    if " " in skill_lower or "-" in skill_lower:
        return skill_lower in resume_text_lower

    # Single-word skills use token matching to avoid partial-word matches.
    return skill_lower in resume_tokens


def score_resume(jd_skills: List[str], resume_text: str):
    resume_text_lower = resume_text.lower()
    resume_tokens = normalize_tokens(resume_text)

    matched, missing = [], []

    for skill in jd_skills:
        if skill_present(skill, resume_text_lower, resume_tokens):
            matched.append(skill)
        else:
            missing.append(skill)

    score = round((len(matched) / len(jd_skills)) * 100) if jd_skills else 0

    return score, matched, missing


def guess_candidate_name(filename: str, resume_text: str) -> str:
    # Use the first sensible non-empty line as the candidate name.
    # Otherwise fall back to the filename.
    for line in resume_text.splitlines():
        line = line.strip()

        if (
            2 <= len(line) <= 60
            and not any(ch.isdigit() for ch in line)
            and "@" not in line
        ):
            return line

    return re.sub(r"\.(pdf|docx|txt)$", "", filename, flags=re.I)


# -----------------------------------------
# API models
# -----------------------------------------

class CandidateResult(BaseModel):
    rank: int
    candidate: str
    score: int
    matched_skills: List[str]
    missing_skills: List[str]


class ScreenResponse(BaseModel):
    results: List[CandidateResult]


# -----------------------------------------
# Routes
# -----------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/screen", response_model=ScreenResponse)
async def screen(
    jd: str = Form(...),
    resumes: List[UploadFile] = File(...),
):
    if not jd.strip():
        raise HTTPException(
            status_code=400,
            detail="Job description is empty.",
        )

    if not resumes:
        raise HTTPException(
            status_code=400,
            detail="At least one resume is required.",
        )

    jd_skills = parse_jd_skills(jd)

    if not jd_skills:
        raise HTTPException(
            status_code=400,
            detail="Could not parse any skills from the JD.",
        )

    scored = []

    for uf in resumes:
        raw = await uf.read()

        if not raw:
            continue

        text = extract_text(uf.filename, raw)
        score, matched, missing = score_resume(jd_skills, text)
        candidate = guess_candidate_name(uf.filename, text)

        scored.append(
            {
                "candidate": candidate,
                "score": score,
                "matched_skills": matched,
                "missing_skills": missing,
            }
        )

    if not scored:
        raise HTTPException(
            status_code=400,
            detail="No readable content found in uploaded resumes.",
        )

    # Highest score first -> assign ranks.
    scored.sort(key=lambda x: x["score"], reverse=True)

    results = [
        CandidateResult(rank=i + 1, **item)
        for i, item in enumerate(scored)
    ]

    return ScreenResponse(results=results)
