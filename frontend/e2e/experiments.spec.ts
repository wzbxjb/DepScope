import { test,expect } from '@playwright/test';
test('displays actual frozen experiment values and separate citation limitations',async({page})=>{
 const response=await page.request.get('http://127.0.0.1:8100/api/experiments/benchmark-v1-20261014');
 expect(response.ok()).toBeTruthy();const recorded=await response.json();
 expect(recorded.manifest.usage.actual_reserved_calls).toBeGreaterThanOrEqual(800);
 await page.goto('/');await page.getByRole('button',{name:'Retrieval experiments',exact:true}).click();
 await expect(page.getByLabel('Experiment run')).toBeVisible();
 const graph=page.getByRole('row').filter({has:page.getByRole('rowheader',{name:'Hybrid + graph',exact:true})});
 await expect(graph.getByRole('cell').first()).toHaveText(`${(recorded.report.methods.graph_rrf.by_split.test.exact_fact_accuracy*100).toFixed(1)}%`);
 await expect(page.getByText(/Semantic citation support is unavailable/)).toBeVisible();
 await page.screenshot({path:'../artifacts/verification/experiments-desktop.png',fullPage:true});
 await page.getByLabel('Experiment split').selectOption('dev');
 await expect(graph.getByRole('cell').first()).toHaveText(`${(recorded.report.methods.graph_rrf.by_split.dev.exact_fact_accuracy*100).toFixed(1)}%`);
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'../artifacts/verification/experiments-mobile.png',fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBeTruthy();
});
