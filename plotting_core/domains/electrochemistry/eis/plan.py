"""eis plotting-only route, using the existing intermediate rendering plan."""
from ...processed_xy import plan as _plan

def build_plan(spec, config, data):
    return _plan.build_plan("eis", spec, config, data)

def qa_checks(plan, data, config, backend_info=None):
    return _plan.qa_checks(plan, data, config, backend_info)

def readme_lines(spec, config):
    return _plan.readme_lines(spec, config)
