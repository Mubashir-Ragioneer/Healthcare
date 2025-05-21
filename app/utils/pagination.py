# app/utils/pagination.py

from pymongo import ASCENDING, DESCENDING

def build_pagination(page: int, page_size: int):
    skip = (page - 1) * page_size
    return skip, page_size

def build_sort(sort_by: str, sort_order: str = "desc"):
    direction = DESCENDING if sort_order == "desc" else ASCENDING
    return [(sort_by, direction)]
