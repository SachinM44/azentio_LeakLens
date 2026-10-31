"""Line categorisation output: one bill category per invoice line, with a flag and an explanation."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.digitisation import remove_additional_properties_from_schema


class NonMedicoPreprocessingItemOutput(BaseModel):
    """Non-medico preprocessing module output - serial_no + categorization fields only."""
    serial_no: int = Field(
        ...,
        description="Serial number of the bill item"
    )
    item_category: str = Field(
        ...,
        description="Billing type from bill_category_list in module config. MUST be exactly one of the values from bill_category_list - no other categories allowed. Extract the authorized list from module_configs (module_name='non_medico_preprocessing', document_name='bill_category_list') and use ONLY those categories. CRITICAL: 'NME' is NOT a valid item_type - it is a classification status."
    )
    flag: str = Field(
        default="no",
        description="'yes' if human review is needed, 'no' if AI is confident"
    )
    confidence_score: float = Field(
        default=0.0,
        description="Confidence score for this specific bill item tagging (0.0 to 1.0)"
    )
    ai_explanation: str = Field(
        default="",
        description="Brief explanation of why this billing category was assigned to the line item (max 150 chars). Must not use pass-through language.",
    )


class NonMedicoPreprocessingData(BaseModel):
    """Non-medico preprocessing data with tagged bill items."""
    tagged_bill_items: List[NonMedicoPreprocessingItemOutput] = Field(
        default_factory=list,
        description="All bill items TAGGED with billing types from list (serial_no + preprocessing-specific fields only)"
    )


class NonMedicoPreprocessingResponse(BaseModel):
    """Response from non-medico preprocessing agent."""
    model_config = ConfigDict(
        json_schema_extra=remove_additional_properties_from_schema
    )

    success: bool = Field(
        ...,
        description="Whether preprocessing was successful"
    )
    preprocessing_data: NonMedicoPreprocessingData = Field(
        ...,
        description="Preprocessing data with tagged bill items and encodings"
    )
    confidence_score: float = Field(
        default=0.0,
        description="Confidence score of the preprocessing (0.0 to 1.0)"
    )
    message: str = Field(
        ...,
        description="Message about the preprocessing process"
    )
    query_raised: bool = Field(
        default=False,
        description="Whether a query was raised"
    )
    query_text: Optional[str] = Field(
        default=None,
        description="Query text if a query was raised"
    )


