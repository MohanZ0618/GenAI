"""Ordered injector registry; order is stable for reproducibility."""

from src.failures.f01_duplicate_invoice import DuplicateInvoiceInjector
from src.failures.f02_po_invoice_amount import POInvoiceAmountInjector
from src.failures.f03_quantity_mismatch import QuantityMismatchInjector
from src.failures.f04_wrong_vendor import WrongVendorInjector
from src.failures.f05_payment_without_invoice import PaymentWithoutInvoiceInjector
from src.failures.f06_double_payment import DoublePaymentInjector
from src.failures.f07_partial_payment import PartialPaymentInjector
from src.failures.f08_approval_failure import ApprovalFailureInjector
from src.failures.f09_gl_mismatch import GLMismatchInjector
from src.failures.f10_wrong_period import WrongPeriodInjector
from src.failures.f11_vendor_change import VendorChangeConflictInjector
from src.failures.f12_erp_payment_missing_bank import ERPPaymentMissingBankInjector
from src.failures.f13_bank_missing_erp import BankMissingERPInjector
from src.failures.f14_bank_erp_amount import BankERPAmountInjector
from src.failures.f15_incorrect_bank_match import IncorrectBankMatchInjector


FAILURE_INJECTORS = [
    DuplicateInvoiceInjector,
    POInvoiceAmountInjector,
    QuantityMismatchInjector,
    WrongVendorInjector,
    PaymentWithoutInvoiceInjector,
    DoublePaymentInjector,
    PartialPaymentInjector,
    ApprovalFailureInjector,
    GLMismatchInjector,
    WrongPeriodInjector,
    VendorChangeConflictInjector,
    ERPPaymentMissingBankInjector,
    BankMissingERPInjector,
    BankERPAmountInjector,
    IncorrectBankMatchInjector,
]

