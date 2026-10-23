"""Write an aggregate weekly CSV; suitable for the clinic host's scheduler."""
import argparse
import os
import sys
import tomllib
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy.exc import SQLAlchemyError
from clinic_data import ClinicStore, make_engine
from analytics import visit_frame, week_bounds, report_csv

ROOT = Path(__file__).resolve().parent


def main():
    secrets_file = ROOT / '.streamlit' / 'secrets.toml'
    secrets = tomllib.loads(secrets_file.read_text()) if secrets_file.exists() else {}
    def setting(key, default=None): return os.environ.get(key, secrets.get(key, default))
    parser = argparse.ArgumentParser(description='Export a clinic weekly summary without patient identifiers.')
    parser.add_argument('--date', type=date.fromisoformat, help='Any date in the reporting week; default is the previous complete week.')
    parser.add_argument('--week-start', choices=['Monday', 'Sunday'], default=setting('REPORT_WEEK_START', 'Monday'))
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    start_day = 6 if args.week_start == 'Sunday' else 0
    today = datetime.now(ZoneInfo('Africa/Lagos')).date()
    reference = args.date or (week_bounds(today, start_day)[0] - timedelta(days=1))
    start, end = week_bounds(reference, start_day)
    url = setting('DATABASE_URL')
    if not url and setting('CLINIC_ENV', 'local').lower() == 'production':
        print('DATABASE_URL is required in production.', file=sys.stderr); return 1
    try:
        store = ClinicStore(make_engine(url or f'sqlite:///{ROOT / "clinic_operations.db"}'))
        content = report_csv(visit_frame(store.visits()), store.incidents(), store.events(), start, end)
    except (SQLAlchemyError, ValueError):
        print('Report generation failed. Check database configuration and connectivity.', file=sys.stderr); return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f'clinic-weekly-{start}.csv'
    output.write_bytes(content)
    print(f'Generated {output.name} for {start} to {end} (Africa/Lagos).')
    return 0


if __name__ == '__main__': raise SystemExit(main())
