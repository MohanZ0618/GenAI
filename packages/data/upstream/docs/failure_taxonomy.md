# Failure taxonomy and injector contracts

Every primary class is implemented in its own `src/failures/f*.py` module behind `FailureInjector.inject(context, case_id)`. An injector selects an unclaimed eligible group, performs a deterministic mutation, propagates downstream effects, appends mutation provenance, adds causal/audit evidence, and returns structured RCA ground truth. A case-local signature test proves the failure exists; GL and bank-statement tests prove fundamental accounting controls remain intact.

## F01 — Duplicate invoice

- **Financial logic:** two records represent one supplier obligation; invoice-number punctuation alone does not make them different economics.
- **Preconditions:** an unpaid invoice and its lines exist and have not been claimed by another case.
- **Mutation:** clone the header and lines under neutral new IDs; normalize punctuation in the supplier reference.
- **Downstream consequences:** the duplicate remains received and is not independently paid or posted, isolating the duplicate-entry risk.
- **Observable symptom:** same vendor, normalized reference, amount, currency, and supporting lines occur twice.
- **True root cause:** AP ingestion entered the same economic document a second time.
- **Evidence:** invoices and invoice lines for the original and duplicate.
- **Resolution:** void the duplicate and improve normalized-reference duplicate controls.
- **Hard negative:** recurring invoices can have the same vendor and amount but distinct references and monthly economic periods.
- **Tests:** normalized references and totals must collide; new IDs and provenance must exist.

## F02 — PO/invoice amount mismatch

- **Financial logic:** an invoice price exceeds the authorized PO without an amendment.
- **Preconditions:** unpaid, unclaimed, PO-backed invoice with at least one matched line.
- **Mutation:** increase a line's unit price and extended amount; update invoice subtotal/total.
- **Downstream consequences:** propagate the new invoice amount into both sides of its invoice journal so invoice arithmetic and GL balance remain valid.
- **Observable symptom:** invoice total and price exceed PO total/line authorization.
- **True root cause:** an unapproved supplier price variance.
- **Evidence:** PO header/lines and invoice header/lines; GL is supporting downstream context.
- **Resolution:** hold payment and obtain a PO amendment or supplier credit.
- **Hard negative:** a one-percent difference inside the configured two-percent tolerance is legitimate.
- **Tests:** invoice internal math and journal balance pass while invoice total exceeds PO total.

## F03 — Quantity mismatch

- **Financial logic:** quantity is a separate control from extended amount.
- **Preconditions:** unpaid PO-backed invoice line with an alternate integer quantity that preserves cent-precision multiplication.
- **Mutation:** replace quantity and set an inverse unit price so extended amount is unchanged.
- **Downstream consequences:** none are needed because invoice total and GL remain unchanged.
- **Observable symptom:** PO and invoice amounts agree while quantities disagree.
- **True root cause:** quantity keying concealed by a compensating unit-price change.
- **Evidence:** matched PO line and invoice line.
- **Resolution:** correct both quantity and unit price from source documentation and rerun three-way match.
- **Hard negative:** split payments or multi-line POs can differ in row count without a quantity error; line linkage must be used.
- **Tests:** quantities differ, extended amounts match, and invoice arithmetic remains valid.

## F04 — Incorrect vendor association

- **Financial logic:** a PO-backed invoice belongs to the PO vendor even when another vendor has a similar profile.
- **Preconditions:** unpaid, unclaimed PO-backed invoice and an alternate vendor with the same currency, preferably the same type.
- **Mutation:** change only the invoice vendor to the alternate vendor.
- **Downstream consequences:** add an AP vendor-selection audit event; the PO retains the authoritative vendor.
- **Observable symptom:** invoice vendor and PO vendor conflict while amounts and currency look plausible.
- **True root cause:** AP ingestion selected a similarly profiled vendor master.
- **Evidence:** invoice, PO, both vendor records, and selection audit event.
- **Resolution:** reassign the invoice, revalidate tax/banking data, and repeat approval.
- **Hard negative:** vendor mergers or documented master changes may legitimately alter names, but the history must support them.
- **Tests:** invoice vendor differs from referenced PO vendor and both vendor IDs resolve.

## F05 — Payment without valid invoice

- **Financial logic:** a cash disbursement requires a supported payable and allocation.
- **Preconditions:** active synthetic vendor and an eligible processing date.
- **Mutation:** insert a completed ad-hoc payment with no allocation.
- **Downstream consequences:** add balanced payment GL lines, a bank debit, and a manual-payment audit event.
- **Observable symptom:** payment, journal, and bank settlement exist but `payment_allocations` has no row.
- **True root cause:** manual AP release without a supporting payable.
- **Evidence:** payment, absence of allocation, journal, bank transaction, and audit event.
- **Resolution:** investigate/recover or document the payment and correct AP/GL.
- **Hard negative:** bank fees have no ERP payment but are valid when separately typed and journaled.
- **Tests:** payment allocation set is empty while payment/GL/bank evidence exists and journal balances.

## F06 — Invoice paid twice

- **Financial logic:** separate successful payment runs settle the same obligation beyond its balance.
- **Preconditions:** fully paid, unclaimed invoice with at least one successful allocation.
- **Mutation:** insert a second full-value payment and allocation.
- **Downstream consequences:** add a balanced payment journal, bank debit, and causal settlement links.
- **Observable symptom:** allocations exceed the invoice total by one full obligation.
- **True root cause:** a later payment run failed to recognize the prior settlement.
- **Evidence:** invoice, both payments/allocations, second journal, and second bank debit.
- **Resolution:** stop/recover and reverse the second payment, then repair paid-status controls.
- **Hard negative:** a scheduled split payment has multiple payments but combined allocations equal, not exceed, the invoice.
- **Tests:** total allocation is greater than invoice total and both disbursement chains exist.

## F07 — Partial payment/residual balance

- **Financial logic:** an invoice cannot be fully settled when successful allocations cover only part of its balance.
- **Preconditions:** unclaimed one-invoice/one-payment settlement, avoiding shared payment side effects.
- **Mutation:** reduce payment and allocation to 60% while leaving invoice status `paid`.
- **Downstream consequences:** reduce the matched bank debit and both payment journal sides to the same partial amount.
- **Observable symptom:** payment, bank, allocation, and GL agree with each other but are below the paid invoice total.
- **True root cause:** invoice status failed to preserve the residual payable.
- **Evidence:** invoice, allocation, payment, journal, and bank transaction.
- **Resolution:** restore the residual, mark partially paid, and schedule or resolve the balance.
- **Hard negative:** intentionally scheduled split payments are valid when all installments together settle the invoice.
- **Tests:** paid status plus allocation below total; payment/GL/bank still reconcile.

## F08 — Approval workflow failure

- **Financial logic:** amount-based policy requires a final approval event before release.
- **Preconditions:** a paid, unclaimed invoice with a generated approval workflow.
- **Mutation:** delete the highest required approval event.
- **Downstream consequences:** retain the payment and add a workflow-override audit event.
- **Observable symptom:** payment exists but the event sequence lacks the level required by invoice value.
- **True root cause:** the payment workflow bypassed the final approval gate.
- **Evidence:** invoice amount, remaining approval events, employee authorities, payment/allocation, and override audit.
- **Resolution:** escalate, obtain review, and repair the enforcement gate.
- **Hard negative:** auto approval below policy threshold is valid when its system event and amount support it.
- **Tests:** count/depth of effective approvals is below policy requirement and payment exists.

## F09 — GL posting mismatch

- **Financial logic:** a balanced journal can still misstate the operational transaction.
- **Preconditions:** unclaimed payment with a normal two-line payment journal.
- **Mutation:** increase both AP debit and cash credit to 103.7% of the payment.
- **Downstream consequences:** bank and operational payment retain the correct amount; double entry remains balanced.
- **Observable symptom:** journal totals disagree with payment/bank although debit equals credit.
- **True root cause:** ERP-to-GL interface posted the wrong amount.
- **Evidence:** payment, payment journal, and bank settlement.
- **Resolution:** reverse and repost from the authoritative payment amount.
- **Hard negative:** cost-center or expense splits can create extra GL lines while journal and source total still agree.
- **Tests:** journal debit equals credit but differs from operational payment.

## F10 — Wrong accounting period

- **Financial logic:** correct amount/account is insufficient if the journal is recognized in the wrong reporting period.
- **Preconditions:** unclaimed payment journal with a valid economic payment date.
- **Mutation:** move every line's posting date and accounting period to the next month.
- **Downstream consequences:** add an interface-queue release audit event; amounts and balance are unchanged.
- **Observable symptom:** balanced journal period differs from payment economic period.
- **True root cause:** period-close interface queue released in the following period.
- **Evidence:** payment date, journal posting date/period, and audit event.
- **Resolution:** move the journal under the organization's period-adjustment policy.
- **Hard negative:** a bank posting after month-end can be legitimate when the GL uses the correct economic payment period.
- **Tests:** all journal lines use a different period than their source payment and remain balanced.

## F11 — Vendor master change conflict

- **Financial logic:** payment instructions must use the vendor version effective at payment creation.
- **Preconditions:** unclaimed payment with a matched bank transaction and current vendor token.
- **Mutation:** set payment and bank counterparty to a superseded token; add a change log from old to current two days before payment.
- **Downstream consequences:** mark settlement failed/bank transaction returned, add processor return audit, and link vendor change to payment.
- **Observable symptom:** rejected settlement used an old token despite a prior verified vendor update.
- **True root cause:** payment snapshot was not refreshed after vendor master change.
- **Evidence:** vendor, change history, payment, returned bank transaction, audit log.
- **Resolution:** regenerate from the effective token and refresh snapshots on master changes.
- **Hard negative:** a payment before the effective change may legitimately use the old token; event order is decisive.
- **Tests:** change old value equals payment token, new value equals vendor current token, change precedes payment, and bank shows return.

## F12 — ERP payment missing from bank

- **Financial logic:** a completed/settled ERP payment beyond clearing window should have external settlement evidence.
- **Preconditions:** unclaimed settled payment with exactly one ordinary bank match.
- **Mutation:** remove the matched bank transaction.
- **Downstream consequences:** retain ERP and GL state; add deterministic transmission, batch-rejection, or release-timeout processor evidence.
- **Observable symptom:** ERP/GL payment exists but no bank debit exists.
- **True root cause:** one of several processor/transmission subcauses retained under F12.
- **Evidence:** payment, absent bank match, payment journal, and processor audit event.
- **Resolution:** reopen settlement state, correct transmission, confirm absence at bank, then resubmit.
- **Hard negative:** a submitted payment one day before cutoff is legitimately pending inside clearing window.
- **Tests:** no non-fee bank row carries the ERP reference and a precise subcause audit event exists.

## F13 — Bank transaction missing from ERP

- **Financial logic:** an outgoing non-fee bank debit requires an ERP payment and accounting trail.
- **Preconditions:** vendor/counterparty context and an eligible bank date/account.
- **Mutation:** insert a manual portal wire with a bank-owned reference and no ERP payment.
- **Downstream consequences:** add bank portal audit evidence but no payment allocation or GL journal; rebuild statements.
- **Observable symptom:** outgoing bank debit cannot link to ERP or GL.
- **True root cause:** treasury user initiated outside the ERP workflow.
- **Evidence:** bank transaction, vendor counterparty, absence in payments/GL, bank audit event.
- **Resolution:** authorize/document and record it, or investigate and recover it.
- **Hard negative:** a separately typed bank fee without an ERP payment is valid when a fee journal exists.
- **Tests:** no payment reference match exists and statement math remains valid after insertion.

## F14 — Bank/ERP amount mismatch

- **Financial logic:** a net bank settlement requires explicit fee/FX accounting; otherwise the source and cash observation disagree.
- **Preconditions:** unclaimed payment with ordinary bank match, amount above fee, and no existing fee row for the reference.
- **Mutation:** lower bank amount by a realistic fixed fee.
- **Downstream consequences:** add processor net-settlement audit evidence but deliberately no fee journal; rebuild statements.
- **Observable symptom:** bank debit is lower than ERP payment and no accounting explanation exists.
- **True root cause:** unconfigured/unrecorded processor fee.
- **Evidence:** payment, bank transaction, GL absence, and settlement audit.
- **Resolution:** approve/post fee accounting and correct settlement configuration.
- **Hard negative:** the same 25-unit difference is non-failure when a balanced fee journal exists.
- **Tests:** amounts differ and no `bank_fee` GL source points to that bank transaction.

## F15 — Incorrect payment-to-bank matching

- **Financial logic:** amount/date/vendor proximity is not enough to disambiguate similar settlements.
- **Preconditions:** two unclaimed, nearby payments to the same vendor and company bank account, preferably within 20% amount difference.
- **Mutation:** swap the two bank rows' ERP payment references.
- **Downstream consequences:** preserve actual clean causal edges while adding the erroneous auto-match audit event.
- **Observable symptom:** each reference points to the other settlement; amount/date evidence becomes misleading.
- **True root cause:** reconciliation automatch selected the wrong candidates.
- **Evidence:** both payments, both bank transactions, allocations, audit event, and causal linkage for evaluation.
- **Resolution:** unmatch both and rematch using reference, amount, date, vendor, and allocation together.
- **Hard negative:** a multi-invoice batch legitimately has one bank row for several obligations when the allocation bridge proves the grouping.
- **Tests:** the affected reference set is preserved but neither payment has its correct amount/reference bank candidate.

## Difficulty policy

- **Easy:** direct two-table evidence, primarily F01–F03 and simple legitimate cases.
- **Medium:** three-system reconciliation or workflow context, primarily F04–F09 and F14.
- **Hard:** audit history, period reasoning, absent records, ambiguous matching, or at least four reasoning hops, primarily F10–F13 and F15.

No-failure difficulty assignments balance the overall distribution toward the target of approximately 30% easy, 45% medium, and 25% hard.

