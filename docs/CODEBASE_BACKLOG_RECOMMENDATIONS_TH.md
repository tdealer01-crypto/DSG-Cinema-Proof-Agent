# แผนแก้ไขและขั้นถัดไป: รายได้อัตโนมัติที่พิสูจน์ได้

เอกสารนี้เป็น **execution plan** จากไฟล์จริงใน repository ณ วันที่ 27 สิงหาคม
2026 ไม่ใช่คำยืนยันสถานะ production ปัจจุบัน หลักฐานที่บันทึกไว้เมื่อ 24 สิงหาคม
บอกว่า Direct API และ Stripe catalog เคยพร้อม แต่ก่อนลงมือแต่ละรอบต้องอ่าน live
`/openapi.json` และ probe endpoint จริงใหม่เสมอ

## เป้าหมายที่ผู้ใช้เห็นและวัดได้

ทำเส้นทางเดียวให้จบก่อน:

```text
เปิดใช้ฟรีโดยไม่ใช้บัตร
  → ได้ API key และ 25 verified proofs
  → ใช้ครบแล้วเห็นปุ่ม/คำสั่งแก้ไขที่ชัดเจน
  → เปิด Stripe-hosted Checkout
  → signed webhook ยืนยันสิทธิ์ metered
  → Z3 พิสูจน์ VERIFIED_GLOBAL_OPTIMUM
  → บันทึก usage หนึ่งหน่วยและส่ง Stripe meter event
  → ผู้ใช้ดู usage ได้ และระบบ reconcile ทุกวัน
```

**North-star metric:** จำนวนบัญชีที่มี `verified proof` อย่างน้อยหนึ่งรายการและมี
payment-backed entitlement ที่ยืนยันแล้วต่อสัปดาห์ ไม่ใช้จำนวน session ที่สร้างหรือ
redirect กลับจาก Checkout เป็นรายได้

Guardrail ที่ห้ามเปลี่ยน: billing ได้เฉพาะ receipt ที่ `verified=true` และมีผล
`VERIFIED_GLOBAL_OPTIMUM`; Checkout redirect ไม่ใช่หลักฐานชำระเงิน และ DSG ต้องไม่
ส่งบัญชีที่ GitHub Marketplace เป็นผู้เก็บเงินเข้า Stripe meter ซ้ำ

## สถานะจากโค้ดที่มีอยู่จริง

| ส่วน | สิ่งที่พบใน repository | สิ่งที่ยังห้ามกล่าวอ้าง |
|---|---|---|
| ราคา | `free` 25 proofs; `metered` self-serve ที่ $0.05 ต่อ verified proof; Team $490 เป็น catalog offer เท่านั้น | Team Checkout พร้อมใช้งาน |
| การเริ่มใช้ | `POST /billing/activate` ออก free entitlement แบบ idempotent และคืน next step | activation production ผ่านโดยไม่ probe |
| browser key | landing เก็บ DSG API key ใน `sessionStorage` เฉพาะ tab, ย้าย key เก่าจาก `localStorage` ออก และมีปุ่ม Forget | การล้าง key ใน browser เท่ากับ revoke key ฝั่ง server |
| การซื้อ | `POST /billing/checkout/session` รองรับเฉพาะ `metered` และคืน `CHECKOUT_CREATED_NOT_ENTITLED` | การสร้าง Session เท่ากับได้เงิน |
| สิทธิ์ | signed, product/price-scoped Stripe webhook เป็นผู้เลื่อน plan | browser success URL เป็น payment proof |
| usage | hash-chained ledger, `/billing/usage`, `/billing/report` และ Stripe meter sync มี implementation/test | settlement หรือรายได้ผ่าน audit แล้ว |
| operation | `Revenue Autopilot` ตรวจ ledger/report ทุกวันและเก็บ artifact 90 วัน | workflow นี้แก้ account, ราคา หรือ entitlement ให้อัตโนมัติ |
| distribution | Direct API ถูกบันทึกว่า live; Stripe App ยัง `READY_FOR_EXTERNAL_UPLOAD` | Stripe App ได้รับอนุมัติหรือ install ได้สาธารณะแล้ว |

ดังนั้นคอขวดที่เหมาะสมไม่ใช่การเปิด marketplace เพิ่ม แต่คือการพิสูจน์ **หนึ่ง paid
conversion จริงแบบ end-to-end** จาก activation ถึง meter reconciliation โดยไม่เกิด
double billing

## แผนลงมือ เรียงตามลำดับที่ปลดล็อกรายได้

### P0 — Gate 0: ยืนยัน production truth ก่อนแก้โค้ด

Owner: ผู้ deploy ที่อ่าน Azure/GitHub production secrets ได้

1. ดึง live `/openapi.json` แล้วตรวจว่ามี `/billing/activate`,
   `/billing/checkout/session`, `/billing/webhook/stripe`, `/billing/usage`,
   `/billing/report` และ `/billing/status` จริง
2. probe `/health` และ `/billing/status`; ต้องเห็น `checkout_status=LINKED`,
   `stripe.link_state=LINKED_VERIFIED`, `charges_enabled=true`,
   `metering_enforced=true`, `enforcement_ready=true` และ blockers ว่าง
3. เก็บ UTC timestamp, deployed revision/commit, HTTP status และ response ที่ลบ secret
   แล้วเป็น artifact เดียว ห้ามคัดค่าจาก manifest มาแทน response

**Exit criterion:** live contract และ operational link ผ่านใน revision เดียวกัน หาก
network หรือ credential เข้าไม่ถึง ให้สถานะ `REVIEW: EVIDENCE_UNAVAILABLE` ไม่ใช่
`BLOCK` และไม่เดาค่า

### P0 — Gate 1: ทำ golden-path purchase หนึ่งบัญชี

Owner: ผู้ถือ Stripe test/live account และ revenue admin secret

1. สร้าง activation id ใหม่ เรียก `/billing/activate` ครั้งแรกและเก็บ API key ที่แสดง
   ครั้งเดียว จากนั้นเรียกซ้ำด้วย activation id เดิม ต้องได้ `409 ACTIVATION_EXISTS`,
   ไม่คืน API key ใหม่ และจำนวน account ต้องคงเดิมตาม idempotency contract
2. ใช้ free proof หนึ่งครั้ง แล้วอ่าน `/billing/usage` เพื่อผูก receipt, account,
   quantity และ ledger sequence
3. เรียก `/billing/checkout/session` ด้วย `plan=metered` และ checkout id คงที่;
   ยืนยันว่า response ยัง `entitled=false`
4. จ่ายผ่าน Stripe-hosted Checkout ด้วยข้อมูลทดสอบที่เหมาะกับ mode จากนั้นรอ signed
   webhook เท่านั้น
5. poll `/billing/subscription` จน entitlement เป็น metered หรือ timeout แบบมีขอบเขต;
   หาก timeout ให้เก็บ Stripe event id และ delivery result แทนการแก้ plan ด้วยมือ
6. ส่ง proof ที่ผ่าน Z3 หนึ่งรายการ ตรวจ local ledger แล้วตรวจว่า meter sync เป็น
   `SYNCED` โดย idempotency key เดิมไม่เพิ่มหน่วยซ้ำ

**Exit criterion:** receipt เดียวเชื่อม `plan_hash/context hash → Z3 proof → ledger
sequence → Stripe meter event id` ได้ และ replay ไม่คิดเงินซ้ำ

### P0 — Gate 2: ทดสอบ failure ที่ป้องกันเงินผิด

เพิ่ม production-like integration tests ก่อนเพิ่ม feature:

- webhook ลายเซ็นผิด, product/price ผิด และ event replay ต้องไม่ให้ paid entitlement
- Checkout ของบัญชี GitHub Marketplace ต้องถูกปฏิเสธเพื่อไม่คิดเงินสองทาง
- solver timeout, `REVIEW`, `BLOCK` และ proof ที่ไม่ใช่ global optimum ต้องเป็นศูนย์หน่วย
- quota race และ request ซ้ำต้อง append ledger/ส่ง meter ได้สูงสุดหนึ่งครั้ง
- Stripe หรือ durable store unavailable ต้อง fail closed พร้อม remediation ที่ผู้ใช้ทำตามได้

**Exit criterion:** tests แสดงทั้ง HTTP result, decision, billing quantity และ ledger
delta ไม่ใช่ assert เพียงข้อความ error

### P1 — Gate 3: ทำ conversion UX ให้จบในหน้าจอเดียว

Direct API/landing เป็น acquisition channel ที่พร้อมกว่าการรอ marketplace จึงทำก่อน:

1. หลัง free activation แสดง `ใช้แล้ว / 25`, ราคาจริง `$0.05 / verified proof` และ
   CTA **Upgrade with Stripe**
2. browser เก็บ key เฉพาะ tab, มีปุ่ม Forget ที่บอกชัดว่าไม่ได้ revoke key ฝั่ง server
   และต้องไม่ส่ง key เข้า log, analytics หรือ URL
3. quota denial ต้องแสดง remediation และเริ่ม Checkout ได้โดยไม่ต้อง copy secret ไปมา
4. หลัง redirect แสดง `Waiting for verified payment` และ poll subscription; ห้ามแสดง
   “Paid” จาก query string
5. หลัง webhook แสดง plan, current usage, last verified receipt และ link ไป billing portal
   เฉพาะเมื่อ route นั้นมีอยู่ใน live OpenAPI จริง
6. emit funnel events ที่ไม่เก็บ API key/Stripe secret: `activation_succeeded`,
   `free_proof_verified`, `checkout_created`, `entitlement_verified`,
   `paid_proof_metered`, `meter_sync_failed`

**Exit criterion:** ผู้ใช้ใหม่ทำ activation → proof → Checkout → paid proof ได้โดยไม่
ต้องอ่าน runbook หรือให้ operator แก้ account

### P1 — Gate 4: ปิดวงจร operation และเงินจริง

1. รัน `Revenue Autopilot` ทุกวันต่อไป แต่ตั้ง alert เมื่อ report unavailable, chain
   invalid, unsynced meter events มากกว่า 0 หรือ Stripe totals ต่างจาก ledger
2. dashboard ต้องแยก `checkout_created`, `entitlement_verified`, `units_metered`,
   Stripe invoice/settlement และ refund; ห้ามรวมเป็นคำว่า revenue ค่าเดียว
3. กำหนด SLO เริ่มต้น: webhook-to-entitlement ≤ 2 นาที, meter sync ≤ 15 นาที,
   reconciliation complete 100% รายวัน และ duplicate billed units = 0
4. ทำ canary paid account ที่มี spending cap; rollback คือปิด paid acquisition ก่อน
   ห้ามลบ ledger หรือ downgrade entitlement แบบเดา

**Exit criterion:** มี daily receipt ที่จับคู่ local billable units กับ Stripe accepted
meter events และมี owner รับ alert

### P2 — ขยายช่องทางหลัง direct funnel ผ่านเท่านั้น

1. Stripe App: upload v2.7.1 แบบ interactive, bind app signing/OAuth secrets, External
   Test, ภาพ Dashboard จริง และ submit review การอนุมัติเป็น distribution milestone
   ไม่ใช่ payment milestone
2. GitHub Marketplace v2: ทดสอบ purchase webhook/account linking ด้วย buyer จริงหนึ่ง
   ราย และพิสูจน์ว่า Cinema Stripe charge เป็นศูนย์ เพราะ GitHub เป็น merchant of record
3. Microsoft Contact-me ใช้เก็บ enterprise lead ได้โดยยังไม่สร้าง billing path ใหม่
4. พัก AWS metering และ Team self-serve จน direct Stripe reconciliation ผ่านต่อเนื่อง
   7 วัน เพราะทั้งสองเพิ่ม pricing/entitlement model ใหม่

## ลำดับงาน 10 วันทำการ

| วัน | งาน | หลักฐานส่งมอบ |
|---:|---|---|
| 1 | Gate 0 และ freeze live contract | redacted probe bundle ผูก commit |
| 2–3 | golden-path ใน Stripe test mode | receipt-to-meter trace หนึ่งเส้น |
| 4–5 | failure/idempotency tests | test report และ ledger deltas |
| 6–7 | activation/usage/Checkout UX | screen recording หรือ screenshots + API trace |
| 8 | production canary แบบจำกัดวงเงิน | signed webhook และ metered proof receipt |
| 9 | reconciliation/alert drill | revenue report artifact + alert receipt |
| 10 | review metrics และ go/no-go | decision record พร้อม evidence links |

หาก Gate ใดไม่ผ่าน งาน downstream ยังอยู่ใน approved plan แต่เปลี่ยนเป็น
`WAITING_PERMISSION` หรือ `REVIEW` ตามชนิดหลักฐาน ไม่ถือว่าแผนทั้งหมดถูกปฏิเสธ

## DSG Decision Frame สำหรับ automation

| สถานการณ์ | ผล | automation ทำอะไร |
|---|---|---|
| action ตรง approved plan, identity/capability พร้อม และ precondition พิสูจน์แล้ว | `ALLOW` | execute แล้วบันทึก evidence/receipt |
| action ตรงแผนแต่ขาด secret, external login หรือ provisioned capability | `WAITING_PERMISSION`, `allowed=true` | แจ้ง prerequisite เดียวที่ขาด แล้ว resume step เดิมโดยไม่ขออนุมัติแผนซ้ำ |
| execution เกิดแล้วแต่ยังผูกหลักฐานถึง claim ไม่ครบ | `REVIEW` | หยุดเฉพาะ claim/charge ที่พิสูจน์ไม่ได้และขอ evidence ที่ขาด |
| plan/agent/action ไม่ตรง หรือขอ claim ที่ระบบไม่รองรับ | `BLOCK` | ปฏิเสธ action นั้นพร้อม exact finding; งานอื่นในแผนยังเดินต่อ |

Z3 เป็นผู้พิสูจน์ decision ภายใต้ constraint ที่ประกาศ ไม่ใช่ผู้พิสูจน์ว่า Stripe รับเงิน
แล้ว หลักฐานการชำระเงินต้องมาจาก signed Stripe event ส่วนหลักฐาน usage ต้องมาจาก
proof-bound ledger แต่ละระบบยืนยันเฉพาะขอบเขตของตน จึงไม่เกิด “ตรัสรู้” จากการนำ
สัญญาณที่ยังไม่ยืนยันมาอนุมานต่อกัน

## Go / no-go ที่เจ้าของผลิตภัณฑ์ตัดสินได้ทันที

**GO paid acquisition** เมื่อ Gate 0–4 ผ่าน, canary จ่ายจริงแบบจำกัดวงเงิน, replay เป็น
ศูนย์หน่วยเพิ่ม และ reconciliation จับคู่ได้ครบ

**NO-GO เฉพาะการรับเงินเพิ่ม** เมื่อ webhook, durable store, meter sync หรือ
reconciliation ใช้งานไม่ได้ ให้ free evaluation/verified execution ที่อยู่ใน approved
plan ทำงานต่อได้ถ้าปลอดภัย และแสดง remediation ตรงจุด ห้าม DSG ปิดทั้งระบบเพียงเพราะ
หลักฐาน billing ส่วนหนึ่งขาด

**ขั้นถัดไปที่เหมาะสมที่สุด:** ทำ Gate 0 แล้ว Gate 1 ด้วย canary หนึ่งบัญชี ก่อนแก้
marketplace หรือเพิ่มราคา เพราะเป็นทางสั้นที่สุดที่เปลี่ยน “ระบบมีโค้ด billing” ให้เป็น
“ผู้ใช้จ่ายและเห็น verified usage ได้จริง” พร้อมหลักฐานที่ตรวจย้อนกลับได้
