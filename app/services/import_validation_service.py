from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.import_draft import (
    ImportDraft,
    ImportDraftItem,
)


class ImportIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ImportValidationIssue:
    code: str
    severity: ImportIssueSeverity
    message: str


@dataclass(frozen=True, slots=True)
class ImportItemValidation:
    item_id: str
    product_name: str
    shortcode: str
    issues: tuple[ImportValidationIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(issue.severity == ImportIssueSeverity.ERROR for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(
            issue.severity == ImportIssueSeverity.WARNING for issue in self.issues
        )

    @property
    def is_blocked(self) -> bool:
        return self.error_count > 0

    @property
    def is_ready(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class ImportDraftValidation:
    selected_count: int
    items: tuple[ImportItemValidation, ...]

    @property
    def error_count(self) -> int:
        return sum(item.error_count for item in self.items)

    @property
    def warning_count(self) -> int:
        return sum(item.warning_count for item in self.items)

    @property
    def blocked_item_count(self) -> int:
        return sum(item.is_blocked for item in self.items)

    @property
    def warning_item_count(self) -> int:
        return sum(
            (not item.is_blocked and item.warning_count > 0) for item in self.items
        )

    @property
    def ready_item_count(self) -> int:
        return sum(item.is_ready for item in self.items)

    @property
    def can_send(self) -> bool:
        return self.selected_count > 0 and self.error_count == 0


class ImportDraftValidationService:
    """
    Preflight validation for the operator review screen.

    Errors block sending to Selora.
    Warnings are informational and do not block outbound imports.

    Missing price is deliberately a warning, not an error:
    outbound Instagram products are allowed to have no known price and
    must never receive a fake zero/placeholder price.
    """

    def validate(
        self,
        *,
        draft: ImportDraft,
    ) -> ImportDraftValidation:
        selected_items = tuple(item for item in draft.items if item.is_selected)

        results = tuple(self._validate_item(item=item) for item in selected_items)

        return ImportDraftValidation(
            selected_count=len(selected_items),
            items=results,
        )

    def _validate_item(
        self,
        *,
        item: ImportDraftItem,
    ) -> ImportItemValidation:
        issues: list[ImportValidationIssue] = []

        product_data = item.product_data

        product_name = ""
        if product_data is not None:
            product_name = product_data.product_name.strip()

        if not product_name:
            issues.append(
                ImportValidationIssue(
                    code="missing_product_name",
                    severity=(ImportIssueSeverity.ERROR),
                    message=("نام محصول وارد نشده است."),
                )
            )

        selected_assets = tuple(
            selected_asset
            for selected_asset in item.selected_assets
            if selected_asset.is_selected
        )

        if not selected_assets:
            issues.append(
                ImportValidationIssue(
                    code="missing_selected_asset",
                    severity=(ImportIssueSeverity.ERROR),
                    message=("هیچ فایلی برای محصول انتخاب نشده است."),
                )
            )

        elif not any(selected_asset.is_primary for selected_asset in selected_assets):
            issues.append(
                ImportValidationIssue(
                    code="missing_primary_asset",
                    severity=(ImportIssueSeverity.WARNING),
                    message=("تصویر اصلی مشخص نشده است."),
                )
            )

        if product_data is None:
            issues.append(
                ImportValidationIssue(
                    code="missing_product_data",
                    severity=(ImportIssueSeverity.ERROR),
                    message=("اطلاعات محصول ساخته نشده است."),
                )
            )

        else:
            if product_data.sale_price is None and product_data.list_price is None:
                issues.append(
                    ImportValidationIssue(
                        code="missing_price",
                        severity=(ImportIssueSeverity.WARNING),
                        message=(
                            "قیمت مشخص نشده است؛ محصول بدون قیمت به staging سلورا می‌رود."
                        ),
                    )
                )

            elif (
                product_data.sale_price is None and product_data.list_price is not None
            ):
                issues.append(
                    ImportValidationIssue(
                        code="missing_sale_price",
                        severity=(ImportIssueSeverity.WARNING),
                        message=("قیمت فروش مشخص نشده است."),
                    )
                )

            if (
                product_data.sale_price is not None
                and product_data.list_price is not None
                and product_data.sale_price > product_data.list_price
            ):
                issues.append(
                    ImportValidationIssue(
                        code="invalid_price_range",
                        severity=(ImportIssueSeverity.ERROR),
                        message=("قیمت فروش از قیمت قبل تخفیف بیشتر است."),
                    )
                )

        return ImportItemValidation(
            item_id=item.id,
            product_name=(product_name or "محصول بدون نام"),
            shortcode=item.media.shortcode,
            issues=tuple(issues),
        )
