"""One local source snapshot per process; no device/test-control interfaces."""
import argparse
import importlib
import json
import math
import sys
from pathlib import Path


def enrich_neware(result, path, output_directory, exporter_path=None):
    """Use explicitly labeled vendor metadata only; retain native data/cycles."""
    metadata=result.setdefault('metadata',{})
    try:
        from .neware_vendor_metadata import extract_active_mass
        evidence=extract_active_mass(path,output_directory,exporter_path=exporter_path)
        if evidence.get('source_sha256') != (result.get('source') or {}).get('sha256'):
            raise ValueError('Vendor mass report source SHA256 differs from the decoded native file')
        value=evidence.get('mass_g')
        if (isinstance(value,bool) or not isinstance(value,(int,float)) or
                not math.isfinite(value) or value<=0 or evidence.get('mass_basis')!='active_material'
                or not isinstance(evidence.get('mass_source'),str) or not evidence['mass_source'].strip()):
            raise ValueError('Vendor report did not provide a positive, labeled active-material mass with source')
        metadata.update(mass_g=value,mass_basis='active_material',mass_source=evidence['mass_source'],
                        vendor_mass_export=dict(status='verified_labeled_report',evidence=evidence))
    except Exception as exc:
        # Native records can still be inspected. Standardization separately
        # requires verified mass or a supplied value with explicit provenance.
        metadata['vendor_mass_export']=dict(status='unavailable',error=str(exc),error_type=type(exc).__name__)
        result.setdefault('issues',[]).append('Active-material mass was not obtained from an isolated manufacturer report: '+str(exc))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor',required=True,choices=('land','neware'))
    parser.add_argument('--file',required=True)
    parser.add_argument('--options',default='{}')
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:
        options=json.loads(args.options)
        if not isinstance(options,dict):
            raise ValueError('Worker options must be an object')
        metadata_export=options.pop('metadata_export',True) if args.vendor=='neware' else False
        exporter_path=options.pop('exporter_path',None) if args.vendor=='neware' else None
        if not isinstance(metadata_export,bool):
            raise ValueError('metadata_export must be boolean')
        if exporter_path is not None and (not isinstance(exporter_path,str) or not Path(exporter_path).is_absolute()):
            raise ValueError('exporter_path must be an absolute installed vendor executable path')
        module=importlib.import_module('.'+args.vendor+'_reader',__package__)
        result=getattr(module,'read_'+args.vendor)(args.file,options=options)
        target=Path(args.output)
        if args.vendor=='neware' and metadata_export:
            enrich_neware(result,args.file,target.parent.parent/('vendor_metadata_'+Path(args.file).stem),exporter_path)
        elif args.vendor=='neware':
            result.setdefault('metadata',{})['vendor_mass_export']=dict(status='disabled_by_request')
        target.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        return 0
    except Exception as exc:
        print(json.dumps(dict(error=str(exc),type=type(exc).__name__),ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
