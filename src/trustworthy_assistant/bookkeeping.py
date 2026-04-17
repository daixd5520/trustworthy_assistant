from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _resolve_tz(tz_name: str):
    if not tz_name or tz_name.lower() == "local":
        return _local_tz()
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return _local_tz()


def _sanitize_job_suffix(value: str) -> str:
    lowered = (value or "").strip().lower()
    sanitized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return sanitized or "user"


def _quantize_amount(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_decimal(value: str | int | float | Decimal) -> Decimal:
    try:
        return _quantize_amount(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid amount: {value}") from exc


def _parse_local_datetime(value: str | None, tz_name: str = "Local") -> datetime:
    tz = _resolve_tz(tz_name)
    if not value:
        return datetime.now(tz=tz)
    text = str(value).strip()
    if not text:
        return datetime.now(tz=tz)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "Invalid occurred_at. Use ISO format like 2026-04-15T18:30:00 or 2026-04-15 18:30."
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


@dataclass(slots=True)
class LedgerEntry:
    entry_id: str
    occurred_at: str
    created_at: str
    entry_type: str
    amount: str
    currency: str
    category: str
    note: str
    source: str
    account: str
    channel: str
    user_id: str


class BookkeepingService:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.base_dir = self.workspace_dir / "bookkeeping"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.base_dir / "ledger.jsonl"
        self.cron_file = self.workspace_dir / "CRON.json"

    def add_entry(
        self,
        *,
        amount: str | int | float,
        category: str,
        entry_type: str = "expense",
        note: str = "",
        occurred_at: str = "",
        currency: str = "CNY",
        source: str = "manual",
        account: str = "cash",
        channel: str = "",
        user_id: str = "",
        tz_name: str = "Local",
    ) -> LedgerEntry:
        normalized_type = str(entry_type or "expense").strip().lower()
        if normalized_type not in {"expense", "income"}:
            raise ValueError("entry_type must be `expense` or `income`.")
        normalized_category = str(category or "").strip()
        if not normalized_category:
            raise ValueError("category must not be empty.")
        occurred_dt = _parse_local_datetime(occurred_at, tz_name=tz_name)
        created_dt = datetime.now(tz=occurred_dt.tzinfo)
        entry = LedgerEntry(
            entry_id=f"txn-{uuid.uuid4().hex[:12]}",
            occurred_at=occurred_dt.isoformat(),
            created_at=created_dt.isoformat(),
            entry_type=normalized_type,
            amount=str(_parse_decimal(amount)),
            currency=(currency or "CNY").strip().upper() or "CNY",
            category=normalized_category,
            note=str(note or "").strip(),
            source=str(source or "manual").strip() or "manual",
            account=str(account or "cash").strip() or "cash",
            channel=str(channel or "").strip(),
            user_id=str(user_id or "").strip(),
        )
        with self.ledger_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    def read_entries(self) -> list[LedgerEntry]:
        if not self.ledger_file.is_file():
            return []
        rows: list[LedgerEntry] = []
        for line in self.ledger_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
                rows.append(LedgerEntry(**payload))
            except Exception:
                continue
        rows.sort(key=lambda item: item.occurred_at)
        return rows

    def summarize(self, period: str, *, tz_name: str = "Local") -> dict:
        normalized = str(period or "").strip().lower()
        if normalized not in {"today", "yesterday", "week", "last_week", "month", "last_month"}:
            raise ValueError("period must be one of today, yesterday, week, last_week, month, last_month.")
        tz = _resolve_tz(tz_name)
        now = datetime.now(tz=tz)
        start, end, label = self._period_bounds(normalized, now)
        entries = []
        for item in self.read_entries():
            try:
                occurred = datetime.fromisoformat(item.occurred_at).astimezone(tz)
            except ValueError:
                continue
            if start <= occurred < end:
                entries.append((item, occurred))
        expense_total = Decimal("0")
        income_total = Decimal("0")
        by_category_expense: dict[str, Decimal] = {}
        by_category_income: dict[str, Decimal] = {}
        latest_rows: list[dict] = []
        for entry, occurred in entries:
            amount = _parse_decimal(entry.amount)
            bucket = by_category_income if entry.entry_type == "income" else by_category_expense
            bucket[entry.category] = bucket.get(entry.category, Decimal("0")) + amount
            if entry.entry_type == "income":
                income_total += amount
            else:
                expense_total += amount
            latest_rows.append(
                {
                    "entry_id": entry.entry_id,
                    "occurred_at": occurred.isoformat(),
                    "entry_type": entry.entry_type,
                    "amount": str(amount),
                    "currency": entry.currency,
                    "category": entry.category,
                    "note": entry.note,
                    "source": entry.source,
                }
            )
        latest_rows.sort(key=lambda row: row["occurred_at"], reverse=True)
        return {
            "period": normalized,
            "label": label,
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "entry_count": len(latest_rows),
            "expense_total": str(_quantize_amount(expense_total)),
            "income_total": str(_quantize_amount(income_total)),
            "net_total": str(_quantize_amount(income_total - expense_total)),
            "expense_by_category": self._serialize_totals(by_category_expense),
            "income_by_category": self._serialize_totals(by_category_income),
            "entries": latest_rows,
        }

    def configure_report_jobs(
        self,
        *,
        channel: str,
        user_id: str,
        tz_name: str = "Local",
        daily_enabled: bool = True,
        weekly_enabled: bool = True,
        monthly_enabled: bool = True,
        daily_time: str = "23:00",
        weekly_time: str = "23:00",
        monthly_time: str = "00:05",
        weekly_weekday: str = "sun",
    ) -> list[dict]:
        if not channel or not user_id:
            raise ValueError("channel and user_id are required for scheduled delivery.")
        daily_hour, daily_minute = self._parse_hhmm(daily_time)
        weekly_hour, weekly_minute = self._parse_hhmm(weekly_time)
        monthly_hour, monthly_minute = self._parse_hhmm(monthly_time)
        weekday_value = self._weekday_to_cron(weekly_weekday)
        suffix = _sanitize_job_suffix(f"{channel}-{user_id}")
        jobs = [
            self._make_job(
                job_id=f"ledger-daily-{suffix}",
                name="Daily Ledger Report",
                enabled=daily_enabled,
                expr=f"{daily_minute} {daily_hour} * * *",
                tz_name=tz_name,
                channel=channel,
                user_id=user_id,
                report_period="today",
                instructions="生成今天的账本总结，包含总支出、总收入、净额、分类统计和简短结论。",
            ),
            self._make_job(
                job_id=f"ledger-weekly-{suffix}",
                name="Weekly Ledger Report",
                enabled=weekly_enabled,
                expr=f"{weekly_minute} {weekly_hour} * * {weekday_value}",
                tz_name=tz_name,
                channel=channel,
                user_id=user_id,
                report_period="week",
                instructions="生成本周账本总结，包含总支出、总收入、净额、分类统计、本周高频消费和简短建议。",
            ),
            self._make_job(
                job_id=f"ledger-monthly-{suffix}",
                name="Monthly Ledger Report",
                enabled=monthly_enabled,
                expr=f"{monthly_minute} {monthly_hour} 1 * *",
                tz_name=tz_name,
                channel=channel,
                user_id=user_id,
                report_period="last_month",
                instructions="生成上个月账单总结，包含总支出、总收入、净额、分类统计、主要消费项目和简短建议。",
            ),
        ]
        data = {"jobs": []}
        if self.cron_file.is_file():
            try:
                data = json.loads(self.cron_file.read_text(encoding="utf-8"))
            except Exception:
                data = {"jobs": []}
        existing = data.get("jobs")
        rows = existing if isinstance(existing, list) else []
        indexed = {str(job.get("id") or ""): job for job in rows if isinstance(job, dict)}
        for job in jobs:
            indexed[job["id"]] = job
        merged_jobs = list(indexed.values())
        merged_jobs.sort(key=lambda item: str(item.get("id") or ""))
        data["jobs"] = merged_jobs
        self.cron_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return jobs

    @staticmethod
    def _serialize_totals(values: dict[str, Decimal]) -> list[dict]:
        rows = [{"category": key, "amount": str(_quantize_amount(val))} for key, val in values.items()]
        rows.sort(key=lambda row: Decimal(row["amount"]), reverse=True)
        return rows

    @staticmethod
    def _period_bounds(period: str, now: datetime) -> tuple[datetime, datetime, str]:
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            return start_of_day, start_of_day + timedelta(days=1), "今日账本"
        if period == "yesterday":
            start = start_of_day - timedelta(days=1)
            return start, start_of_day, "昨日账本"
        if period == "week":
            start = start_of_day - timedelta(days=start_of_day.weekday())
            return start, start + timedelta(days=7), "本周账本"
        if period == "last_week":
            end = start_of_day - timedelta(days=start_of_day.weekday())
            return end - timedelta(days=7), end, "上周账本"
        month_start = start_of_day.replace(day=1)
        if period == "month":
            if month_start.month == 12:
                next_month = month_start.replace(year=month_start.year + 1, month=1)
            else:
                next_month = month_start.replace(month=month_start.month + 1)
            return month_start, next_month, "本月账本"
        if month_start.month == 1:
            prev_month_start = month_start.replace(year=month_start.year - 1, month=12)
        else:
            prev_month_start = month_start.replace(month=month_start.month - 1)
        return prev_month_start, month_start, "上月账单"

    @staticmethod
    def _parse_hhmm(value: str) -> tuple[int, int]:
        text = str(value or "").strip()
        match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text)
        if not match:
            raise ValueError(f"Invalid time `{value}`. Use HH:MM, e.g. 23:00.")
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _weekday_to_cron(value: str) -> int:
        normalized = str(value or "sun").strip().lower()
        mapping = {
            "sun": 0,
            "sunday": 0,
            "mon": 1,
            "monday": 1,
            "tue": 2,
            "tuesday": 2,
            "wed": 3,
            "wednesday": 3,
            "thu": 4,
            "thursday": 4,
            "fri": 5,
            "friday": 5,
            "sat": 6,
            "saturday": 6,
        }
        if normalized not in mapping:
            raise ValueError("weekly_weekday must be one of sun, mon, tue, wed, thu, fri, sat.")
        return mapping[normalized]

    @staticmethod
    def _make_job(
        *,
        job_id: str,
        name: str,
        enabled: bool,
        expr: str,
        tz_name: str,
        channel: str,
        user_id: str,
        report_period: str,
        instructions: str,
    ) -> dict:
        return {
            "id": job_id,
            "name": name,
            "enabled": enabled,
            "channel": channel,
            "sender_id": user_id,
            "schedule": {
                "kind": "cron",
                "expr": expr,
                "tz": tz_name or "Local",
            },
            "payload": {
                "kind": "agent_turn",
                "message": (
                    f"请调用 `ledger_report(period=\"{report_period}\")` 获取账本数据。"
                    f"{instructions}"
                    "如果该周期没有任何账目，也请明确说明本周期暂无记账记录。"
                ),
            },
            "delete_after_run": False,
        }
