"""Calibrated SEM crop/scale plans and editable native Illustrator AI output."""
import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','render'))
    parser.add_argument('--spec',required=True,help='Absolute SEM request JSON; separate from curve PlotSpec')
    args=parser.parse_args(argv)
    try:
        path=Path(args.spec)
        if not path.is_absolute():
            raise ValueError('SEM spec must be an absolute path')
        document=json.loads(path.read_text(encoding='utf-8-sig'))
        from .sem.service import check_sem,execute_sem
        if args.command=='check':
            result=dict(ready=True,stage='validated_sem_plan',plan=check_sem(document),adobe_executed=False)
        else:
            result=execute_sem(document)
    except Exception as exc:
        result=dict(ready=False,stage='request_or_plan',errors=[str(exc)],adobe_executed=False)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['ready'] else 2


if __name__=='__main__':
    sys.exit(main())
