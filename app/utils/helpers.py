"""通用辅助函数：分页、CSV 导出、文件校验等。"""
from __future__ import annotations
import csv
import hashlib
import os
from io import StringIO
from typing import Iterable, Sequence
from flask import Response, current_app


def paginate(query, page: int, per_page: int):
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    total = query.order_by(None).count()
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def csv_response(headers: Sequence[str], rows: Iterable[Sequence[str]], filename: str = "export.csv") -> Response:
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(r)
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def allowed_file(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config.get("ALLOWED_EXTENSIONS", set())


def file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
