"""Parse every workflow before content checks. Offline, no secrets or state.

This checks YAML and necessary Actions structure; GitHub acceptance and natural
execution remain separate. Never execute workflow shell strings or expressions.
"""
import json
from pathlib import Path
import re
import yaml


class WorkflowLoader(yaml.SafeLoader):
    pass


# Actions uses `on` as a key, not the YAML 1.1 implicit boolean `true`.
WorkflowLoader.yaml_implicit_resolvers={key:[(tag,rx) for tag,rx in values if tag!='tag:yaml.org,2002:bool']
                                        for key,values in yaml.SafeLoader.yaml_implicit_resolvers.items()}
WorkflowLoader.add_implicit_resolver('tag:yaml.org,2002:bool',re.compile(r'^(?:true|false)$',re.I),list('tTfF'))


def unique_mapping(loader,node,deep=False):
    loader.flatten_mapping(node)
    result={}
    for key_node,value_node in node.value:
        key=loader.construct_object(key_node,deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(None,None,'duplicate workflow mapping key',key_node.start_mark)
        result[key]=loader.construct_object(value_node,deep=deep)
    return result


WorkflowLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,unique_mapping)


def parse_workflow(text):
    data=yaml.load(text,Loader=WorkflowLoader)
    if not isinstance(data,dict) or not data.get('on') or not isinstance(data.get('jobs'),dict) or not data['jobs']:
        raise ValueError('workflow needs triggers and nonempty jobs')
    def env(value):
        if value is not None and (not isinstance(value,dict) or any(isinstance(v,(dict,list)) for v in value.values())):
            raise ValueError('env must be a scalar mapping')
    env(data.get('env'))
    trigger=data['on']
    if isinstance(trigger,dict) and trigger.get('schedule') is not None:
        schedule=trigger['schedule']
        if not isinstance(schedule,list) or not schedule:
            raise ValueError('schedule must be a nonempty cron list')
        for row in schedule:
            if not isinstance(row,dict) or not isinstance(row.get('cron'),str) or len(row['cron'].split())!=5:
                raise ValueError('invalid cron structure')
    for job in data['jobs'].values():
        if not isinstance(job,dict):raise ValueError('job must be a mapping')
        env(job.get('env'))
        needs=job.get('needs',[])
        needs=[needs] if isinstance(needs,str) else needs
        if not isinstance(needs,list) or any(key not in data['jobs'] for key in needs):raise ValueError('unknown needs job')
        if 'uses' in job:continue
        if not job.get('runs-on') or not isinstance(job.get('steps'),list) or not job['steps']:
            raise ValueError('job needs runner and nonempty steps')
        for step in job['steps']:
            if not isinstance(step,dict) or ('uses' in step)==('run' in step):raise ValueError('step needs exactly one uses or run')
            env(step.get('env'))
    return data


def check(directory=Path('.github/workflows')):
    paths=sorted([*Path(directory).glob('*.yml'),*Path(directory).glob('*.yaml')])
    if not paths:raise ValueError('no workflow files')
    for path in paths:
        try:
            data=parse_workflow(path.read_text(encoding='utf-8-sig'))
            if path.name=='realtime-monitors.yml':
                steps=[step for job in data['jobs'].values() for step in job.get('steps',[])]
                runtime=next(s for s in steps if s.get('name')=='Run all realtime monitors independently')
                if runtime.get('env',{}).get('CONTENT_PREFLIGHT_STRICT')!='1':raise ValueError('strict flag missing from runtime step')
        except (yaml.YAMLError,ValueError,TypeError,StopIteration,KeyError) as exc:
            # Do not dump environment values or shell bodies into generic logs.
            raise ValueError(path.name+': '+type(exc).__name__) from None
    return {'workflows_parsed':len(paths),'yaml_and_required_structure':'passed',
            'discord_sends':0,'production_state_access':False,'github_natural_execution':'pending'}


if __name__=='__main__':
    print(json.dumps(check()))
