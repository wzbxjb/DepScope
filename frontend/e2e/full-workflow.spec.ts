import { createHash } from 'node:crypto';
import { test,expect } from '@playwright/test';
import { readFile,writeFile,copyFile } from 'node:fs/promises';
test.use({video:'on'});
test('shows scoped evidence through the complete product',async({page,request})=>{
 test.setTimeout(300000);page.setDefaultTimeout(10000);
 await page.goto('/');await page.getByRole('button',{name:'Load verified public sample'}).first().click();
 await expect(page.getByTestId('graph-scope')).toBeVisible();await expect(page.getByText('langchain-community',{exact:true})).toBeVisible();await expect(page.getByText('Preparing evidence',{exact:true})).not.toBeVisible();await page.waitForLoadState('networkidle');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Advisory matches',exact:true}).click();
 await page.setViewportSize({width:1440,height:1024});await page.locator('.finding-card').first().click();
 await expect(page.getByRole('heading',{name:'Recorded impact paths'})).toBeVisible();await expect(page.locator('.evidence-detail').getByRole('link',{name:'Source record ↗'})).toBeVisible();
 const name='release-observed-'+Date.now();let project='';
 try{
  await page.getByRole('button',{name:'New project',exact:true}).click();await page.getByRole('textbox',{name:'Project name'}).fill(name);
  const created=page.waitForResponse(r=>r.url().endsWith('/api/projects')&&r.request().method()==='POST');await page.getByRole('button',{name:'Create project',exact:true}).click();project=(await(await created).json()).id;
  await expect(page.getByLabel('Project',{exact:true})).toHaveValue(project);const snapshots:string[]=[];
  for(const file of ['backend','backend','example']){
   await page.getByRole('button',{name:'Add snapshot'}).click();const dialog=page.getByRole('dialog');const uploaded=page.waitForResponse(r=>r.url().endsWith('/imports')&&r.request().method()==='POST');await dialog.locator('input[type=file]').setInputFiles(`../artifacts/corpus/${file}-environment.cdx.json`);expect((await uploaded).status()).toBe(202);const raw=await readFile(`../artifacts/corpus/${file}-environment.cdx.json`);const digest=createHash('sha256').update(raw).digest('hex');const sid=createHash('sha256').update(JSON.stringify([project,'observed_environment',digest])).digest('hex');await expect.poll(async()=>(await request.get('/api/snapshots/'+sid)).status(),{timeout:90000}).toBe(200);snapshots.push(sid);await expect(page.getByLabel('Snapshot',{exact:true})).toHaveValue(sid);await expect(page.getByText('Preparing evidence',{exact:true})).not.toBeVisible();await page.waitForLoadState('networkidle');
  }
  expect(snapshots[0]).toBe(snapshots[1]);expect(snapshots[2]).not.toBe(snapshots[0]);const inventory=await(await request.get(`/api/projects/${project}/snapshots?limit=100`)).json();expect(inventory.items).toHaveLength(2);
  await page.getByRole('button',{name:'Compare snapshots',exact:true}).first().click();await page.getByLabel('Baseline snapshot').selectOption(snapshots[0]);await page.getByLabel('Candidate snapshot').selectOption(snapshots[2]);await page.locator('.compare-picker').getByRole('button',{name:'Compare snapshots'}).click();
  await expect(page.getByText('metadata comparison',{exact:true})).toBeVisible({timeout:90000});await expect(page.getByText('New known matches',{exact:true})).toBeVisible();await page.screenshot({path:'../artifacts/verification/release-workflow.png',fullPage:true});
  await page.getByRole('button',{name:'Retrieval experiments',exact:true}).click();await expect(page.getByLabel('Experiment run')).toBeVisible();await expect(page.getByText(/800 recorded calls/)).toBeVisible();
  await writeFile('../artifacts/verification/full-workflow-result.json',JSON.stringify({status:'passed',source_kind:'observed_environment',source_files:['backend-environment.cdx.json','example-environment.cdx.json'],same_file_snapshot_idempotent:true,actual_snapshot_count:inventory.items.length,comparison_level:'metadata_comparison',experiment_run_id:'benchmark-v1-20261014',paid_calls_in_this_test:0,observed_at:new Date().toISOString()},null,2)+'\n');
 }finally{
  if(project){const {spawnSync}=await import('node:child_process');const cleaned=spawnSync('../backend/.venv/bin/python',['-c',`
import sys
from depscope.runtime.config import load_settings
from depscope.graph.driver import connect
with connect(load_settings()) as driver:
 with driver.session() as s:
  p,n=sys.argv[1:];assert n.startswith('release-observed-')
  assert s.run('MATCH (p:Project {id:$p,name:$n}) RETURN p',p=p,n=n).single()
  for query in ['MATCH (c:Comparison)-[:BASELINE|CANDIDATE]->(s:Snapshot {project_id:$p}) DETACH DELETE c','MATCH (r:MatchRun {project_id:$p})-[:HAS_FINDING]->(f) DETACH DELETE f','MATCH (r:MatchRun {project_id:$p}) DETACH DELETE r','MATCH (c:ComponentInstance {project_id:$p}) DETACH DELETE c','MATCH (s:Snapshot {project_id:$p}) DETACH DELETE s','MATCH (p:Project {id:$p,name:$n}) DETACH DELETE p']:
   s.run(query,p=p,n=n).consume()
`,project,name],{encoding:'utf8'});expect.soft(cleaned.status,cleaned.stderr).toBe(0);}
 }
 const video=page.video();await page.context().close();if(video)await copyFile(await video.path(),'../artifacts/verification/product-demo.webm');
});
test('explicit live generation has a locatable original source',async({page})=>{
 test.skip(process.env.DEPSCOPE_LIVE_GENERATION!=='1','Paid generation requires explicit opt-in.');test.setTimeout(240000);
 const sample=JSON.parse(await readFile('../artifacts/verification/public-demo.json','utf8'));const status=await(await page.request.get('/api/ai/status')).json();expect(status.generation).toBe('configured');expect(status.budget.remaining_calls).toBeGreaterThan(0);
 await page.goto('/');await page.getByLabel('Project',{exact:true}).selectOption(sample.project_id);await page.getByLabel('Snapshot',{exact:true}).selectOption(sample.snapshot_id);await page.getByLabel('Advisory query run').selectOption(sample.run_id);await page.getByRole('button',{name:'AI investigation',exact:true}).click();await page.getByLabel('Retrieval method').selectOption('lexical');await page.getByLabel('Investigation question').fill('How many recorded instances are in this snapshot? Report the instances metric.');await expect(page.getByRole('button',{name:'Ask with evidence'})).toBeEnabled();await page.getByRole('button',{name:'Ask with evidence'}).click();await expect(page.getByTestId('investigation-answer')).toContainText('Evidence-based answer',{timeout:210000});await page.getByRole('button',{name:/Evidence 1 /}).click();await expect(page.getByRole('heading',{name:'Original source field verified'})).toBeVisible();await page.screenshot({path:'../artifacts/verification/release-live-answer.png',fullPage:true});
});
