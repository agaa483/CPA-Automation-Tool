from pydantic import BaseModel, Field, model_validator


class AuditDecision(BaseModel):
    is_correct: bool
    corrected_category: str | None = None
    reasoning: str = Field(..., min_length=1)
    supporting_email_ids: list[str] = []

    @model_validator(mode="after")
    def _require_corrected_when_incorrect(self) -> "AuditDecision":
        if self.is_correct is False and not self.corrected_category:
            raise ValueError(
                "corrected_category is required when is_correct is False"
            )
        return self
