"""Раздача медиа-файлов с поддержкой Range-запросов.

django.views.static.serve отдаёт весь файл целиком даже на запрос
с Range: браузеру видео приходится скачивать файл до конца, чтобы
перемотать плеер. Этот модуль реализует частичную раздачу (206) —
стандарт для видео-хостингов и требование плеера.

Заодно закрывает раздачу кэш-заголовком (имена файлов уникальны,
кэш на сутки безопасен) и защищает путь от обхода каталога.
"""

from __future__ import annotations

import mimetypes
import os
import re

from django.http import FileResponse, Http404, HttpResponse
from django.utils.http import http_date

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class _RangeReader:
    """Читает из файла не более length байт с текущей позиции.

    FileResponse стримит от текущей позиции до конца файла; для ответа
    с частичным содержимым этого мало — нужен ещё лимит, иначе на
    запрос bytes=0-99 уедет весь файл.
    """

    def __init__(self, fileobj, length: int):
        self._file = fileobj
        self._remaining = length

    def read(self, size=-1):
        if self._remaining <= 0:
            return b""
        if size is None or size < 0:
            size = self._remaining
        else:
            size = min(size, self._remaining)
        data = self._file.read(size)
        self._remaining -= len(data)
        return data

    def close(self):
        self._file.close()


def serve_public_media(request, path, document_root=None):
    """Отдаёт файл с поддержкой Range; приватные пути — 404."""
    normalized_path = path.replace("\\", "/").lstrip("/")
    if normalized_path.startswith("private_media/"):
        raise Http404("Файл доступен только через защищённый маршрут.")

    document_root = os.path.abspath(document_root or "")
    full_path = os.path.abspath(os.path.join(document_root, normalized_path))

    # Защита от обхода каталога: путь обязан остаться внутри MEDIA_ROOT.
    if not full_path.startswith(document_root + os.sep) and full_path != document_root:
        raise Http404("Файл не найден.")

    if not os.path.isfile(full_path):
        raise Http404("Файл не найден.")

    stat = os.stat(full_path)
    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"

    file = open(full_path, "rb")
    range_header = request.META.get("HTTP_RANGE", "").strip()
    match = _RANGE_RE.match(range_header) if range_header else None

    if match:
        start_s, end_s = match.groups()
        try:
            if start_s and end_s:
                start, end = int(start_s), min(int(end_s), stat.st_size - 1)
            elif start_s:
                start, end = int(start_s), stat.st_size - 1
            elif end_s:
                # bytes=-N: последние N байт.
                start, end = max(0, stat.st_size - int(end_s)), stat.st_size - 1
            else:
                start, end = 0, stat.st_size - 1
            if start > end or start >= stat.st_size:
                raise ValueError
        except ValueError:
            file.close()
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{stat.st_size}"
            return response

        file.seek(start)
        response = FileResponse(
            _RangeReader(file, end - start + 1), content_type=content_type
        )
        response.status_code = 206
        response["Content-Range"] = f"bytes {start}-{end}/{stat.st_size}"
        response["Content-Length"] = str(end - start + 1)
    else:
        # Непотребный формат Range (или его отсутствие) — весь файл.
        response = FileResponse(file, content_type=content_type)
        response["Content-Length"] = str(stat.st_size)

    response["Accept-Ranges"] = "bytes"
    response["Last-Modified"] = http_date(stat.st_mtime)
    response["Cache-Control"] = "public, max-age=86400"
    return response
