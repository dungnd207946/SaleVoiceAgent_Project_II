"""Đọc Postgres — quyết định "cái gì cần index".

RLS lọc tenant, nhưng không lọc `status`: điều kiện `published` ở cả hai phía (record và
anchor cha) là việc của tầng này.
"""
