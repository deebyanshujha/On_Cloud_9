from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScholarCredentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=256)


class ScholarLogin(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


class ScholarProfile(BaseModel):
    id: int
    email: str
    username: str
    full_name: str | None = None
    organization: str | None = None
    organization_id: str | None = None
    phone_number: str | None = None
    experience: str | None = None
    role: str = "scholar"
    created_at: datetime | None = None


class AuthSession(BaseModel):
    access_token: str
    token_type: str = "bearer"
    profile: ScholarProfile


class ScholarProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    organization: str | None = Field(default=None, max_length=160)
    organization_id: str | None = Field(default=None, max_length=120)
    phone_number: str | None = Field(default=None, max_length=40)
    experience: str | None = Field(default=None, max_length=1000)


class ScholarContributionCreate(BaseModel):
    title: str = Field(min_length=4, max_length=180)
    summary: str = Field(min_length=20, max_length=4000)
    drug: str | None = Field(default=None, max_length=120)
    disease: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=500)


class ScholarContributionOut(BaseModel):
    id: int
    title: str
    summary: str
    drug: str | None
    disease: str | None
    source_url: str | None
    author_name: str
    organization: str | None
    created_at: datetime | None
