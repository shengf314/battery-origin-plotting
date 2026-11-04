"""Read selected NEWARE NDA/NDAX records without deduplication or interpolation.

Supported binary layouts: NDAX data.ndc v2/v5 type1; NDA v29 and v130.
The byte layout/scaling follows NewareNDA 2026.6.11 (BSD-3-Clause),
https://github.com/d-cogswell/NewareNDA. See THIRD_PARTY_LICENSE below.
This implementation uses only Python's standard library, keeps physical record
order/native counters, and does not call NewareNDA's convenience API (which can
deduplicate, sort, regenerate cycles, or interpolate sparse newer formats).
"""

import hashlib
import json
import math
import struct
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

READER_VERSION = "1.0.0"
LAYOUT_SOURCE = "https://github.com/d-cogswell/NewareNDA"
LAYOUT_VERSION = "2026.6.11"
STATE = {1:"CC_Chg",2:"CC_DChg",3:"CV_Chg",4:"Rest",5:"Cycle",7:"CCCV_Chg",
         8:"CP_DChg",9:"CP_Chg",10:"CR_DChg",13:"Pause",16:"Pulse",17:"SIM",
         19:"CV_DChg",20:"CCCV_DChg",21:"Control",22:"OCV",26:"CPCV_DChg",27:"CPCV_Chg"}
CHARGE = {1,3,7,9,27}
DISCHARGE = {2,8,10,19,20,26}
REST = {4,5,13,21,22}
MULTIPLIER = {-100000000:10.,0:0.}
for _code in (-200000,-100000,-60000,-30000,-50000,-40000,-20000,-12000,-10000,
              -6000,-5000,-3000,-2000,-1000):
    MULTIPLIER[_code]=1e-2
for _code in (-500,-100): MULTIPLIER[_code]=1e-3
for _code in (-50,-25,-20,-10): MULTIPLIER[_code]=1e-4
for _code in (-5,-2,-1): MULTIPLIER[_code]=1e-5
for _code in (1,2,5): MULTIPLIER[_code]=1e-4
for _code in (10,20,25,50): MULTIPLIER[_code]=1e-3
for _code in (100,200,250,500): MULTIPLIER[_code]=1e-2
for _code in (1000,6000,10000,12000,20000,30000,40000,50000,60000,100000,200000):
    MULTIPLIER[_code]=1e-1


class NewareReadError(ValueError):
    """An unsupported or malformed format, never permission to repair data."""


def _hash(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            value.update(block)
    return value.hexdigest()


def _branch(code):
    return 'charge' if code in CHARGE else 'discharge' if code in DISCHARGE else 'rest' if code in REST else 'unknown'


def _timestamp(parts):
    try:
        return datetime(*parts).isoformat(sep=' ')
    except ValueError as exc:
        raise NewareReadError('Invalid native calendar timestamp: %r' % (parts,)) from exc


def _calendar_record(payload,offset,layout):
    """Decode the shared v29 NDA / v2,v5 NDC measured-record payload."""
    if layout=='ndc':
        index,cycle,step,code=struct.unpack_from('<IIBB',payload,8)
        elapsed,voltage,current=struct.unpack_from('<Qii',payload,23)
        qcharge,qdischarge,echarge,edischarge=struct.unpack_from('<qqqq',payload,43)
        stamp=struct.unpack_from('<HBBBBB',payload,75)
        scale=struct.unpack_from('<i',payload,82)[0]
    else:
        index,cycle,step,code=struct.unpack_from('<IIHB',payload,2)
        elapsed,voltage,current=struct.unpack_from('<Qii',payload,14)
        qcharge,qdischarge,echarge,edischarge=struct.unpack_from('<qqqq',payload,38)
        stamp=struct.unpack_from('<HBBBBB',payload,70)
        scale=struct.unpack_from('<i',payload,78)[0]
    if scale not in MULTIPLIER:
        raise NewareReadError('Unsupported NEWARE current range %s at byte %s; no scale is guessed' % (scale,offset))
    if code not in STATE:
        raise NewareReadError('Unsupported NEWARE state code %s at byte %s' % (code,offset))
    multiplier=MULTIPLIER[scale]
    return dict(record_index=index,native_cycle=cycle,cycle=cycle+1,native_step=step,
                status_code=code,mode=STATE[code],branch=_branch(code),
                voltage_V=voltage/10000.,current_mA=current*multiplier,
                charge_capacity_mAh=qcharge*multiplier/3600.,
                discharge_capacity_mAh=qdischarge*multiplier/3600.,
                charge_energy_mWh=echarge*multiplier/3600.,
                discharge_energy_mWh=edischarge*multiplier/3600.,
                step_time_s=elapsed/1000.,test_time_s=None,timestamp=_timestamp(stamp),
                byte_offset=offset,native_current_range=scale)


def _ndax_records(archive,metadata):
    info=archive.getinfo('data.ndc')
    if info.file_size>4*1024**3:
        raise NewareReadError('data.ndc exceeds this reader\'s explicit 4GiB limit')
    data=archive.read('data.ndc')
    if len(data)<525:
        raise NewareReadError('Truncated NDAX data.ndc header')
    kind,version=data[0],data[2]
    metadata.update(ndc_version=version,ndc_filetype=kind,data_member='data.ndc',
                    data_member_sha256=hashlib.sha256(data).hexdigest())
    if kind!=1 or version not in (2,5):
        raise NewareReadError('Unsupported NDAX NDC version %s type %s; sparse v11/14/16/17 needs vendor export; no interpolation is performed' % (version,kind))
    if any(name in archive.namelist() for name in ('data_runInfo.ndc','data_step.ndc')):
        raise NewareReadError('Split/sparse NDAX fields require a separately validated native export')
    if version==2:
        if len(data)%512:
            raise NewareReadError('NDAX v2 block is incomplete')
        declared=0
        for block_start in range(512,len(data),512):
            block=data[block_start:block_start+512]
            block_type,count,mask=struct.unpack_from('<HHB',block,0)
            if block_type!=2 or count>5 or mask&~31 or bin(mask).count('1')!=count:
                raise NewareReadError('Unsupported NDAX v2 page header at byte %s; no signature scanning or record skipping occurs' % block_start)
            declared+=count
            for slot in range(5):
                if not (mask&(1<<slot)): continue
                position=block_start+5+slot*94
                payload=data[position:position+94]
                if len(payload)!=94 or payload[0]!=0x55:
                    raise NewareReadError('Malformed NDAX measured record at byte %s' % position)
                yield _calendar_record(payload,position,'ndc')
        metadata['native_page_record_count']=declared
    else:
        if len(data)%4096:
            raise NewareReadError('NDAX v5 block is incomplete')
        for block_start in range(4096,len(data),4096):
            block=data[block_start:block_start+4096]
            for item_start in range(125,4040,87):
                payload=block[item_start:item_start+87]
                if payload[7:8]==b'\x55':
                    yield _calendar_record(payload,block_start+item_start,'ndc')
                elif any(payload):
                    # Non-record block slots may carry padding; retain a count
                    # for audit rather than treating them as measured records.
                    metadata['non_measured_slots']=metadata.get('non_measured_slots',0)+1


def _nda_records(path,metadata):
    data=path.read_bytes()
    if len(data)<1024 or data[:6]!=b'NEWARE':
        raise NewareReadError('Not a NEWARE NDA file or truncated header')
    version=data[14]
    metadata['nda_version']=version
    if version==29:
        raw_mass=struct.unpack_from('<I',data,152)[0]
        metadata['native_mass_candidate']=dict(value=raw_mass/1000.,unit='mg',
                 basis='parser_reports_active_mass; input convention unconfirmed',
                 source='NDA bytes152:156 uint32 /1000 per NewareNDA '+LAYOUT_VERSION,
                 raw_integer=raw_mass)
    elif version==130:
        footer=data.rfind(b'\x06\x00\xf0\x1d\x81\x00\x03\x00\x61\x90\x71\x90\x02\x7f\xff\x00',1024)
        if footer!=-1 and footer+16+499<=len(data):
            raw_mass=struct.unpack_from('<d',data,footer+16+491)[0]
            if math.isfinite(raw_mass):
                metadata['native_mass_candidate']=dict(value=raw_mass,unit='mg',
                    basis='parser_reports_active_mass; input convention unconfirmed',
                    source='NDA130 footer+16+491 float64 per NewareNDA '+LAYOUT_VERSION)
    if version==29:
        length=86
        identifier=b'\x00\x00\x00\x00\x55\x00'
        header=data.find(identifier)
        while header!=-1 and header+4+length<len(data):
            start=header+4
            if data[start+length]==0x55 and data[start+12]!=0:
                break
            header=data.find(identifier,header+4)
        if header==-1:
            raise NewareReadError('NDA v29 measured-record alignment not found')
        for start in range(header+4,len(data)-length+1,length):
            payload=data[start:start+length]
            # This format places auxiliary records in the same stream. Only
            # measured 0x55 records have these fields; no observation is deduped.
            if payload[0:2]==b'\x55\x00' and payload[82:86]==b'\x00'*4:
                yield _calendar_record(payload,start,'nda29')
            elif payload[0:1]==b'\x65':
                metadata['native_auxiliary_records']=metadata.get('native_auxiliary_records',0)+1
            elif any(payload):
                metadata['non_measured_slots']=metadata.get('non_measured_slots',0)+1
    elif version==130:
        first=data[1024:1030]
        if first[0:1]==b'\x55':
            length=data.find(first[:2],1026)-1024
            if length not in (56,):
                raise NewareReadError('Unsupported NDA v130 BTS9.1 record width %s' % length)
            metadata['nda_record_width']=length
            for offset in range(1024,len(data)-length+1,length):
                payload=data[offset:offset+length]
                if payload[0]==0x81:
                    break
                if payload[0]!=0x55:
                    if any(payload): metadata['non_measured_slots']=metadata.get('non_measured_slots',0)+1
                    continue
                step,code=struct.unpack_from('<BB',payload,2)
                index,elapsed,nanos=struct.unpack_from('<III',payload,8)
                current,voltage,capacity,energy,cycle=struct.unpack_from('<ffffI',payload,20)
                seconds,date_nanos=struct.unpack_from('<II',payload,44)
                if code not in STATE:
                    raise NewareReadError('Unsupported NDA state %s' % code)
                yield dict(record_index=index,native_cycle=cycle,cycle=cycle+1,native_step=step,
                           status_code=code,mode=STATE[code],branch=_branch(code),
                           voltage_V=voltage,current_mA=current,
                           charge_capacity_mAh=max(capacity,0)/3600.,
                           discharge_capacity_mAh=-min(capacity,0)/3600.,
                           charge_energy_mWh=max(energy,0)/3600.,
                           discharge_energy_mWh=-min(energy,0)/3600.,
                           native_signed_capacity=capacity,native_signed_energy=energy,
                           step_time_s=elapsed+nanos*1e-9,test_time_s=None,
                           timestamp=datetime.fromtimestamp(seconds+date_nanos*1e-9,timezone.utc).isoformat(),
                           byte_offset=offset)
        else:
            length=88
            metadata.update(nda_record_width=length,cycle_source='not_stored_in_NDA130_BTS9')
            for offset in range(1024,len(data)-length+1,length):
                payload=data[offset:offset+length]
                if payload[0]==0x81: break
                if payload[:6]!=first:
                    if any(payload): metadata['non_measured_slots']=metadata.get('non_measured_slots',0)+1
                    continue
                raw=payload[4:]
                step,code=struct.unpack_from('<BB',raw,5)
                index=struct.unpack_from('<I',raw,12)[0]
                elapsed,voltage,current=struct.unpack_from('<Qff',raw,24)
                qc,ec,qd,ed,stamp=struct.unpack_from('<ffffQ',raw,48)
                if code not in STATE: raise NewareReadError('Unsupported NDA state %s' % code)
                yield dict(record_index=index,native_cycle=None,cycle=None,native_step=step,
                           status_code=code,mode=STATE[code],branch=_branch(code),
                           voltage_V=voltage,current_mA=current,
                           charge_capacity_mAh=qc/3600.,discharge_capacity_mAh=qd/3600.,
                           charge_energy_mWh=ec/3600.,discharge_energy_mWh=ed/3600.,
                           step_time_s=elapsed/1e6,test_time_s=None,
                           timestamp=datetime.fromtimestamp(stamp/1e6,timezone.utc).isoformat(),byte_offset=offset)
    else:
        raise NewareReadError('Unsupported NDA version %s; supported versions are 29 and selected 130 layouts' % version)


def _xml_metadata(archive):
    result={}
    for name in archive.namelist():
        if not name.lower().endswith('.xml'): continue
        payload=archive.read(name)
        if len(payload)>4*1024**2:
            raise NewareReadError('Metadata XML exceeds explicit 4MiB limit: '+name)
        try:
            text=payload.decode('gb18030') if b'GB2312' in payload[:160].upper() else payload.decode('utf-8-sig')
            tree=ET.fromstring(text)
        except (UnicodeError,ET.ParseError) as exc:
            raise NewareReadError('Malformed NDAX metadata XML: '+name) from exc
        def element(node):
            return dict(tag=node.tag,attributes=dict(node.attrib),text=node.text.strip() if node.text and node.text.strip() else None,
                        children=[element(child) for child in node])
        result[name]=element(tree)
    return result


def read_neware(path,options=None):
    """Return native records and explicit metadata without scientific inference.

    options: include_records (default True); records_output (new JSONL path).
    JSONL mode with include_records=False limits memory while keeping all records.
    No mass is inferred from unitless BatteryMass/SCQ fields in vendor metadata.
    Native cycle is zero-based in validated layouts; cycle adds one only, never
    reconstructs charge-first cycles. Resets/duplicates are retained and flagged.
    """
    path=Path(path)
    if not path.is_file(): raise NewareReadError('NEWARE input file does not exist: '+str(path))
    options=dict(options or {})
    extra=set(options)-{'include_records','records_output'}
    if extra: raise NewareReadError('Unsupported NEWARE reader option: '+', '.join(sorted(extra)))
    include=options.get('include_records',True)
    if not isinstance(include,bool): raise NewareReadError('include_records must be boolean')
    before=_hash(path)
    metadata=dict(reader='stdlib-neWare-preserving',reader_version=READER_VERSION,
                  layout_source=LAYOUT_SOURCE,layout_version=LAYOUT_VERSION,
                  mass_g=None,mass_basis='unknown',mass_source='No documented mass unit is inferred from native metadata',
                  capacity_basis='step_cumulative',cycle_source='native_zero_based_counter_plus_one',
                  cycle_capacity_basis='sum_of_native_step_endpoints',
                  cycle_summary_source='explicit arithmetic over native counter groups; not a native software cycle-summary export',
                  step_source='contiguous native cycle/program-step/state runs; native_step also retained',
                  time_basis='native step elapsed time; no accumulated test time invented',
                  records_reordered=False,records_deduplicated=False,records_interpolated=False,
                  native_cycle_reset_detected=False,native_cycle_contains_multiple_branch_pairs=False)
    suffix=path.suffix.lower()
    archive=None
    if suffix=='.ndax':
        try:
            archive=zipfile.ZipFile(str(path))
            if archive.namelist().count('data.ndc')!=1: raise NewareReadError('NDAX must have one unambiguous data.ndc')
            metadata['native_xml']=_xml_metadata(archive)
            metadata['archive_members']=[dict(name=info.filename,bytes=info.file_size,crc32=info.CRC) for info in archive.infolist()]
            metadata['unparsed_binary_members']=[name for name in archive.namelist() if name.endswith('.ndc') and name!='data.ndc']
            iterator=_ndax_records(archive,metadata)
        except (zipfile.BadZipFile,KeyError) as exc:
            raise NewareReadError('Invalid NDAX ZIP structure') from exc
    elif suffix=='.nda':
        iterator=_nda_records(path,metadata)
    else:
        raise NewareReadError('NEWARE input must be .nda or .ndax')
    records=[]
    steps=[]
    issues=[]
    seen=set()
    previous=None
    last_index=None
    last_cycle=None
    step_number=0
    count=0
    output=None
    output_path=Path(options['records_output']) if options.get('records_output') else None
    if output_path:
        if output_path.resolve()==path.resolve(): raise NewareReadError('Output cannot overwrite the engineering input')
        output_path.parent.mkdir(parents=True,exist_ok=True)
        output=output_path.open('x',encoding='utf-8')
    try:
        for row in iterator:
            index=row['record_index']
            count+=1
            if row['branch']=='unknown':
                state_issue='unclassified_native_state:'+row['mode']
                if state_issue not in issues: issues.append(state_issue)
            if index in seen and 'duplicate_native_record_index' not in issues:
                issues.append('duplicate_native_record_index')
            seen.add(index)
            if last_index is not None and index<last_index and 'native_record_index_decreased' not in issues:
                issues.append('native_record_index_decreased')
            last_index=index
            cycle=row['cycle']
            if cycle is not None and last_cycle is not None and cycle<last_cycle:
                metadata['native_cycle_reset_detected']=True
            if cycle is not None: last_cycle=cycle
            identity=(row['native_cycle'],row['native_step'],row['status_code'])
            if identity!=previous:
                step_number+=1
                steps.append(dict(step=step_number,cycle=cycle,native_step=row['native_step'],
                                  branch=row['branch'],mode=row['mode'],first_record=index,last_record=index,
                                  capacity_mAh=0.,record_count=0))
                previous=identity
            row.update(step=step_number,source_record_ordinal=count,
                       specific_capacity_mAh_g=None)
            if row['branch']=='charge': row['capacity_mAh']=row['charge_capacity_mAh']
            elif row['branch']=='discharge': row['capacity_mAh']=row['discharge_capacity_mAh']
            else: row['capacity_mAh']=None
            if not all(math.isfinite(row[key]) for key in ('voltage_V','current_mA','charge_capacity_mAh','discharge_capacity_mAh','step_time_s')):
                raise NewareReadError('Nonfinite native field at record %s; no filtering performed' % index)
            step=steps[-1]
            step.update(last_record=index,record_count=step['record_count']+1,
                        capacity_mAh=row['capacity_mAh'],last_source_ordinal=count)
            if output: output.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
            if include: records.append(row)
    finally:
        if output: output.close()
        if archive: archive.close()
    if not count: raise NewareReadError('No measured native records found')
    after=_hash(path)
    if after!=before: raise NewareReadError('NEWARE engineering input changed during reading')
    cycles=[]
    branch_history={}
    for item in steps:
        if item['branch'] not in ('charge','discharge'): continue
        history=branch_history.setdefault(item['cycle'],[])
        if not history or history[-1]!=item['branch']:
            history.append(item['branch'])
        if len(history)>2:
            metadata['native_cycle_contains_multiple_branch_pairs']=True
    if metadata['native_cycle_reset_detected']:
        issues.append('native_cycle_counter_resets; explicit cycle definition is required before cycle/rate grouping')
    elif metadata['native_cycle_contains_multiple_branch_pairs']:
        issues.append('native_cycle_contains_multiple_charge_discharge_pairs; explicit cycle definition is required before cycle/rate grouping')
    elif any(item['cycle'] is None for item in steps):
        issues.append('native_cycle_counter_unavailable; explicit cycle definition is required')
    else:
        grouped=OrderedDict()
        for step in steps:
            group=grouped.setdefault(step['cycle'],dict(cycle=step['cycle'],charge_capacity_mAh=None,discharge_capacity_mAh=None,
                        charge_specific_capacity_mAh_g=None,discharge_specific_capacity_mAh_g=None,ce_percent=None))
            if step['branch'] in ('charge','discharge'):
                key=step['branch']+'_capacity_mAh'
                # Step-cumulative quantities are summed across explicit CC/CV
                # segments; retain every segment in steps for independent QA.
                group[key]=(group[key] or 0.)+step['capacity_mAh']
        for group in grouped.values():
            qc,qd=group['charge_capacity_mAh'],group['discharge_capacity_mAh']
            if qc is not None and qc>0 and qd is not None: group['ce_percent']=qd/qc*100.
        cycles=list(grouped.values())
    return dict(vendor='neware',format=suffix[1:],source=dict(file=str(path.resolve()),sha256=before,bytes=path.stat().st_size),
                metadata=metadata,records=records,records_file=str(output_path.resolve()) if output_path else None,
                record_count=count,steps=steps,cycles=cycles,
                units=dict(voltage_V='V',current_mA='mA',capacity_mAh='mAh',
                           charge_capacity_mAh='mAh',discharge_capacity_mAh='mAh',
                           specific_capacity_mAh_g='mAh/g',step_time_s='s',test_time_s='s'),issues=issues)


THIRD_PARTY_LICENSE = """
Byte layouts and scaling adapted from NewareNDA 2026.6.11.
Copyright (c) 2022-2024 SES AI Corporation, All rights reserved.
Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software without
   specific prior written permission.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.
"""
