"""Persist structural exploration and its exact query independently of runs."""
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def save_pathways(root,result):
    folder=Path(root)/('pathways-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    config={key:result[key] for key in ('request','case_id','model_version','experiment','scope') if key in result}
    for name,data in [('config.json',config),('pathways.json',result)]:
        (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return folder
