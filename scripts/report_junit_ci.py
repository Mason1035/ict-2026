"""Expose pytest failures as GitHub annotations as well as retained JUnit artifacts."""
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

def escape(text):return text.replace('%','%25').replace('\r','%0D').replace('\n','%0A')
def report(path):
    path=Path(path)
    if not path.is_file():
        print('::error::Backend JUnit report missing; inspect collection/install logs')
        return
    root=ET.parse(path).getroot()
    for case in root.iter('testcase'):
        for kind in ('failure','error'):
            failure=case.find(kind)
            if failure is not None:
                name=case.get('classname','')+'.'+case.get('name','')
                detail=(failure.get('message','')+'\n'+(failure.text or ''))[-6500:]
                print('::error title='+escape(name)+'::'+escape(detail))
    suites=[root] if root.tag=='testsuite' else list(root.iter('testsuite'))
    summary='\n'.join(str({k:s.get(k) for k in ('tests','failures','errors','skipped')}) for s in suites)
    print(summary)
    import os
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write('Backend JUnit summary\n\n'+summary+'\n')

if __name__=='__main__':report(sys.argv[1])
