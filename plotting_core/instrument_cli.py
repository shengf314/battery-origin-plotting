"""Experimental LAND/NEWARE import; prepare existing standard plotting inputs."""
import argparse
import json
import sys
from .instruments.service import read_json,run_import,record_request_failure,UnsafeInstrumentOutput


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('inspect','prepare'))
    parser.add_argument('--request',help='Absolute JSON request for prepare or multi-file inspect')
    parser.add_argument('--input',help='One absolute measured project file for inspect')
    parser.add_argument('--vendor',choices=('auto','land','neware'),default='auto')
    parser.add_argument('--output-root',required=True,help='Independent absolute task directory')
    parser.add_argument('--render',action='store_true',help='After standardization invoke the existing Origin pipeline; image acceptance remains separate')
    args=parser.parse_args(argv)
    if bool(args.request)==bool(args.input):
        parser.error('Provide exactly one --request or --input')
    if args.command=='prepare' and not args.request:
        parser.error('prepare requires --request for explicit plot type, grouping and scientific metadata')
    if args.command=='inspect' and args.render:
        parser.error('inspect never starts Origin')
    try:
        request=(read_json(args.request) if args.request else
                 dict(schema_version=1,sources=[dict(file=args.input,vendor=args.vendor)]))
        outcome=run_import(request,args.output_root,inspection=args.command=='inspect',render=args.render)
    except UnsafeInstrumentOutput as exc:
        outcome=dict(ready=False,stage='request',errors=[str(exc)],questions=[],
                     import_accepted=False,origin_executed=False)
    except (ValueError,OSError,TypeError) as exc:
        try:
            outcome=record_request_failure(args.output_root,exc,args.request)
        except (ValueError,OSError) as report_error:
            outcome=dict(ready=False,stage='request',errors=[str(exc),str(report_error)],questions=[],import_accepted=False,origin_executed=False)
    fields=('ready','stage','import_accepted','origin_executed','task_dir','plot_spec','questions','errors')
    print(json.dumps({key:outcome.get(key) for key in fields},ensure_ascii=False,indent=2))
    return 0 if outcome['ready'] else 2


if __name__=='__main__':
    sys.exit(main())
