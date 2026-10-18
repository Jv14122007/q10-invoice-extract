
import re
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1)


class InvoiceResult(BaseModel):
    vendor: str
    amount: float
    currency: str
    date: str


def extract_invoice(text: str) -> InvoiceResult:
    text = text.strip()

    if not text:
        raise HTTPException(status_code=422, detail="Invoice text is empty")

    # Extract vendor from common invoice labels.
    vendor = None
    vendor_patterns = [
        r"(?im)^\s*(?:vendor|supplier|seller|company)\s*:\s*(.+?)\s*$",
        r"(?im)^\s*(?:from|billed\s+by|issued\s+by)\s*:\s*(.+?)\s*$",
        r"(?im)^\s*vendor\s+name\s*:\s*(.+?)\s*$",
    ]

    for pattern in vendor_patterns:
        match = re.search(pattern, text)
        if match:
            vendor = match.group(1).strip().strip('"\'')
            break

    # Fallback: detect a company-style name in the text.
    if not vendor:
        match = re.search(
            r"\b([A-Z][A-Za-z0-9&'-]*(?:-[A-Za-z0-9]+)*"
            r"(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,7}"
            r"\s+(?:Industries|Inc\.?|LLC|Ltd\.?|Limited|"
            r"Corporation|Corp\.?|Company|Co\.?))\b",
            text,
        )
        if match:
            vendor = match.group(1).strip()

    # Find currency from explicit code or symbol.
    currency_match = re.search(
        r"(?i)\b(USD|EUR|GBP)\b|([$€£])",
        text,
    )
    currency = None
    if currency_match:
        currency = currency_match.group(1)
        if not currency:
            currency = {
                "$": "USD",
                "€": "EUR",
                "£": "GBP",
            }.get(currency_match.group(2))

    # Find amount near total due / amount due / balance due.
    amount_patterns = [
        r"(?i)(?:total\s+due|amount\s+due|balance\s+due|"
        r"grand\s+total|invoice\s+total|total\s+payable)"
        r"\s*[:=]?\s*(?:USD|EUR|GBP|[$€£])?\s*"
        r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"(?i)(?:USD|EUR|GBP)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"[$€£]\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    ]

    amount = None
    for pattern in amount_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                amount = float(match.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    # Prefer a payment due date over invoice/issue dates.
    date_patterns = [
        r"(?i)(?:payment\s+)?due\s+date\s*[:=]?\s*"
        r"(\d{4}-\d{2}-\d{2})",
        r"(?i)(?:pay\s+by|due\s+on|payment\s+due)\s*[:=]?\s*"
        r"(\d{4}-\d{2}-\d{2})",
        r"\b(2026-\d{2}-\d{2})\b",
    ]

    due_date = None
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1)
            try:
                date.fromisoformat(candidate)
                due_date = candidate
                break
            except ValueError:
                continue

    if not vendor or amount is None or not currency or not due_date:
        raise HTTPException(
            status_code=422,
            detail="Could not extract all required invoice fields",
        )

    return InvoiceResult(
        vendor=vendor,
        amount=amount,
        currency=currency.upper(),
        date=due_date,
    )


@app.post("/extract", response_model=InvoiceResult)
def extract(request: ExtractRequest):
    return extract_invoice(request.text)
