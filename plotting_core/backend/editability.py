"""Actually edit native objects in an isolated copy, save and reopen that copy."""

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

from . import native_text


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _text(value):
    # LabTalk text$ assignment preserves its native \l()/\n notation. Doubling
    # those backslashes would change the saved linked legend content.
    return str(value).replace('"', '\\"').replace('\r', '').replace('\n', '\\n')


def probe(backend, project_path, plan, config, evidence_dir):
    """The final OPJU and exports stay untouched; this is an API operation probe.

    The copy is edited and saved with changed curve properties, an axis title,
    linked legend and any scientific annotation. Source XY values are compared
    exactly after reopening. This does not claim a manual GUI interaction test.
    """
    original = Path(project_path).resolve()
    directory = Path(evidence_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    copy = directory / 'editability_probe.opju'
    evidence = directory / 'editability_probe.json'
    original_hash = _digest(original)
    original_legend = getattr(backend, '_legend_text', None)
    original_semantic_legend = getattr(backend, '_semantic_legend_text', None)
    original_legend_state = deepcopy(getattr(backend, '_legend_state', None))
    probe_plan = deepcopy(plan)
    report = {'ok': False, 'issues': [], 'project': str(copy),
              'evidence': str(evidence), 'operations': [],
              'method': 'native API edits in task-copy + save/reload + exact data verification',
              'original': str(original), 'original_sha256_before': original_hash}
    operations = report['operations']
    try:
        shutil.copy2(str(original), str(copy))
        initial = backend.verify_project(str(copy), plan, config)
        if not initial['ok']:
            raise RuntimeError('probe copy initial verification failed: %s' % initial['issues'])
        backend.run('win -a %s; layer -s 1;' % backend.graph_name)
        # Exercise one data curve for every native Y binding side.
        ordinals, seen_sides = {}, set()
        for item in plan.series:
            layer = item.layer + 1
            ordinals[layer] = ordinals.get(layer, 0) + 1
            if item.y_axis in seen_sides:
                continue
            seen_sides.add(item.y_axis)
            ordinal = ordinals[layer]
            backend.run('layer -s %d; layer.plot=%d; get %%C -c editBeforeColor;' % (layer, ordinal))
            before = backend.value('editBeforeColor')
            backend.run('set %C -c color(1,2,3); get %C -c editAfterColor;')
            after = backend.value('editAfterColor')
            if after == before:
                raise RuntimeError('native curve property did not change')
            operations.append({'kind': 'curve_color', 'layer': layer, 'ordinal': ordinal,
                               'y_axis': item.y_axis, 'before': before, 'after': after})
        backend.run('layer -s 1;')
        before_title = backend.text('xb.text$')
        # Independently change the copy's scientific expectation. The saved
        # title may already contain Origin's bold serialization; do not reuse
        # that readback as semantic input or nest it inside another bold wrapper.
        bottom_axis = probe_plan.layers[0].axes.get('bottom') if probe_plan.layers else None
        if bottom_axis is None or not bottom_axis.label:
            raise RuntimeError('editability axis-title probe requires a planned bottom title')
        title = str(bottom_axis.label) + ' [edit probe]'
        bottom_axis.label = title
        backend.run('xb.text$="%s";' % _text(title))
        from ..style import typography
        native_text.apply_native_text_bold(backend, 'xb', typography.axis_title_bold(config))
        native_title_after = backend.text('xb.text$')
        operations.append({'kind': 'axis_title', 'object': 'xb', 'before': before_title,
                           'semantic_after': title, 'after': native_title_after})
        if original_legend is not None:
            name = backend._legend_object
            legend = original_legend + '\\nEDITPROBE'
            # text$ assignment alone can leave literal \n in a single visual
            # line. Use native Label -sa to perform its documented conversion.
            backend.run('label -sl -sa -n %s "%s";' % (name, _text(legend.replace('\\n', '\n'))))
            from ..style import typography
            backend.run('%s.font=font(%s); %s.fsize=%s;' %
                        (name, typography.font_family(config), name, typography.legend_size_pt(config)), expect=False)
            native_text.apply_native_text_bold(backend, name, typography.legend_bold(config))
            backend._legend_text = legend
            backend._semantic_legend_text = legend
            native_legend_after = backend.text('%s.text$' % name)
            operations.append({'kind': 'legend_text', 'object': name, 'before': original_legend,
                               'semantic_after': legend, 'after': native_legend_after})
        for label in probe_plan.labels:
            if label.render != 'native' or label.role.startswith('axis_title') or not label.position:
                continue
            before = backend.text('%s.text$' % label.name)
            label.text = label.text + ' [edit probe]'
            backend.run('%s.text$="%s";' % (label.name, _text(label.text)))
            native_text.apply_native_text_bold(backend, label.name, typography.annotation_bold(config))
            x, y = label.position
            if label.anchor == 'x_scale_y_fraction':
                y = backend.value('layer.y.from') + y * (backend.value('layer.y.to') - backend.value('layer.y.from'))
            backend.run('%s.x=%s; %s.y=%s;' % (label.name, x, label.name, y), expect=False)
            operations.append({'kind': 'annotation_text', 'object': label.name, 'before': before,
                               'semantic_after': label.text, 'after': backend.text('%s.text$' % label.name)})
            break
        if original_legend_state is not None:
            # Probe text is intentionally larger. Position its final native
            # frame before capture; compare against this changed copy's state.
            from .native_legend import place_legend
            backend._legend_state = place_legend(backend, probe_plan, config, backend._area_mm, backend._legend_object)
        for arrow in probe_plan.page.get('native_arrows') or []:
            name=arrow['name']
            backend.run('layer -s %d;' % (arrow['layer']+1))
            before=backend.value('%s.y1' % name)
            arrow['tail'][1]+=0.01
            after=backend.value('layer.y.from')+arrow['tail'][1]*(backend.value('layer.y.to')-backend.value('layer.y.from'))
            backend.run('%s.y1=%.17g; draw -n %s -u;' % (name,after,name))
            operations.append({'kind':'arrow_endpoint','object':name,'property':'y1','layer':arrow['layer']+1,'before':before,'after':after})
        backend.app.Save(str(copy))
        reopened = backend.verify_project(str(copy), probe_plan, config)
        report['reopened'] = reopened
        if not reopened['ok']:
            report['issues'].extend(reopened['issues'])
        for operation in operations:
            if operation['kind'] == 'curve_color':
                backend.run('layer -s %d; layer.plot=%d; get %%C -c editReopenedColor;' %
                            (operation['layer'], operation['ordinal']))
                actual = backend.value('editReopenedColor')
            elif operation['kind']=='arrow_endpoint':
                backend.run('layer -s %d;' % operation['layer'])
                actual=backend.value('%s.%s' % (operation['object'],operation['property']))
            else:
                backend.run('layer -s 1;')
                actual = backend.text('%s.text$' % operation['object'])
            operation['reopened'] = actual
            def normalized(value):
                return value.replace('\\n', '\n').replace('\r\n', '\n').strip() if isinstance(value, str) else value
            operation['persisted'] = normalized(actual) == normalized(operation['after'])
            if not operation['persisted']:
                report['issues'].append('%s native edit did not persist' % operation['kind'])
    except Exception as exc:
        report['issues'].append(str(exc))
    finally:
        backend._legend_text = original_legend
        backend._semantic_legend_text = original_semantic_legend
        backend._legend_state = original_legend_state
        try:
            report['restored_original'] = backend.verify_project(str(original), plan, config)
            if not report['restored_original']['ok']:
                report['issues'].append('original project could not be restored/verified')
        except Exception as exc:
            report['issues'].append('original project restore failed: %s' % exc)
        report['original_sha256_after'] = _digest(original)
        report['original_unchanged'] = report['original_sha256_after'] == original_hash
        if not report['original_unchanged']:
            report['issues'].append('final project changed during the copy probe')
        report['ok'] = not report['issues'] and bool(operations)
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
