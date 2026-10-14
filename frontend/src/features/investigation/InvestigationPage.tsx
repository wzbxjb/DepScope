import { useCallback,useEffect,useRef,useState } from 'react';
import { BookOpen,MessageSquare,Send,ShieldCheck } from 'lucide-react';
import { request } from '../../api/client';
import { JobProgress } from '../../components/JobProgress';
import type { Job,Comparison } from '../../api/types';
import './investigation.css';

type Scope={project_ids:string[];snapshot_ids:string[];run_map:Record<string,string>;comparison_id:string|null};
type Fact={kind:string;value:Record<string,unknown>;source_ids:string[]};
type Answer={status:string;body:string;facts:Fact[];citations:string[];limitations:string[];model_id:string|null;request_id:string|null;usage:Record<string,number>|null;explanation_verified:boolean;supplied_evidence_ids:string[]};
type RecordResult={id:string;question:string;scope:Scope;answer:Answer;observed_at:string};
type Status={generation:string;embedding:string;budget:{call_count:number;remaining_calls:number;estimated_spent:string|null;currency:string;unknown_usage_calls?:number;max_amount?:string;max_calls?:number}};
type Proof={chunk:{text:string;pointer:string;start:number;end:number;source_ids:string[]};source_verified:boolean;source_observations:{uri:string;digest:string;observed_at:string}[];original_field_excerpt:string;upstream_source_ids:string[];upstream_pointer:string|null};
const labels:Record<string,string>={answered:'Evidence-based answer',insufficient_evidence:'Evidence is insufficient',unsupported_output:'Unsupported output withheld',parse_error:'Model output could not be read',generation_error:'Model service failed',budget_exhausted:'Session limit reached',retrieval_error:'Evidence retrieval failed',needs_scope:'Select a scope'};

export function InvestigationPage({projectId,snapshotId,runId,comparison}:{projectId:string;snapshotId:string;runId:string;comparison?:Comparison}) {
  const [question,setQuestion]=useState('');const [method,setMethod]=useState('graph_rrf');const [includeComparison,setIncludeComparison]=useState(false);
  const [limitCalls,setLimitCalls]=useState(40);const [limitAmount,setLimitAmount]=useState('10');
  const [status,setStatus]=useState<Status>();const [pending,setPending]=useState(false);const [jobId,setJobId]=useState('');const [result,setResult]=useState<RecordResult>();const [error,setError]=useState('');const [proof,setProof]=useState<Proof>();
  const scope:Scope=includeComparison&&comparison?{project_ids:[projectId],snapshot_ids:[comparison.baseline_id,comparison.candidate_id],run_map:{[comparison.baseline_id]:comparison.run_ids[0],[comparison.candidate_id]:comparison.run_ids[1]},comparison_id:comparison.id}:{project_ids:[projectId],snapshot_ids:[snapshotId],run_map:{[snapshotId]:runId},comparison_id:null};
  const scopeKey=JSON.stringify(scope);const current=useRef(scopeKey);current.current=scopeKey;
  const refreshStatus=useCallback(()=>request<Status>('/api/ai/status').then(setStatus).catch(reason=>setError(reason.message)),[]);
  useEffect(()=>{void refreshStatus();},[refreshStatus]);
  useEffect(()=>{setResult(undefined);setProof(undefined);setError('');setJobId('');setPending(false);},[scopeKey]);
  const onDone=useCallback((job:Job)=>{
    setJobId('');setPending(false);void refreshStatus();
    if(job.status!=='ready'||!job.result_id){setError(job.error?.message??'Investigation ended without a result');return;}
    const requested=scopeKey;
    void request<RecordResult>(`/api/investigations/${job.result_id}`).then(value=>{
      if(current.current!==requested)return;
      if(JSON.stringify(value.scope)!==requested){setError('The answer scope differs from your selection');return;}
      setResult(value);
    }).catch(reason=>{if(current.current===requested)setError(reason.message);});
  },[scopeKey,refreshStatus]);
  const ask=async()=>{
    const selected=scopeKey;setPending(true);setError('');setResult(undefined);setProof(undefined);
    try{
      const response=await request<{job_id?:string;status?:string}>('/api/investigations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,scope,method})});
      if(current.current!==selected)return;
      if(!response.job_id)throw new Error('Select an explicit investigation scope');
      setJobId(response.job_id);
    }catch(reason){if(current.current===selected){setError((reason as Error).message);setPending(false);}}
  };
  const openProof=async(id:string)=>{
    if(!result)return;const selected=scopeKey;
    try{const value=await request<Proof>(`/api/investigations/${result.id}/evidence/${id}`);if(current.current===selected)setProof(value);}
    catch(reason){if(current.current===selected)setError((reason as Error).message);}
  };
  const available=Boolean(projectId&&snapshotId&&runId&&status?.generation==='configured'&&status?.embedding==='configured');
  return <section className="investigation-page"><div className="panel-heading"><div><span className="eyebrow">SCOPED INVESTIGATION</span><h2><MessageSquare size={20}/> Ask the evidence.</h2><p>Get a generated explanation with checked facts and original source fields.</p></div><span className="tag">Read-only investigation</span></div>
    <div className="ai-budget"><ShieldCheck size={17}/><span>{status?`${status.budget.remaining_calls} calls remaining · ${status.budget.call_count} recorded calls`:'Loading session limits'}<small>{status?.budget.estimated_spent!==null&&status?.budget.estimated_spent!==undefined?`Estimated cost: ${status.budget.currency} ${status.budget.estimated_spent}`:'Cost unavailable until reliable usage is recorded'} · Persisted across restarts</small></span></div>
    {!runId&&<p className="notice">Select an advisory query run before asking a question.</p>}{status?.generation==='not_configured'&&<p className="notice">Configure your private model API key to enable investigations.</p>}{status?.embedding==='not_configured'&&<p className="notice">The local evidence embedding model is not configured.</p>}
    <form onSubmit={event=>{event.preventDefault();void ask();}} className="question-form"><label>Investigation question<textarea aria-label="Investigation question" rows={3} value={question} onChange={event=>setQuestion(event.target.value)} maxLength={5000} placeholder="Which recorded dependencies connect this application to the advisory?" required/></label><div className="question-controls"><label>Retrieval method<select aria-label="Retrieval method" value={method} onChange={event=>setMethod(event.target.value)}><option value="graph_rrf">Hybrid + graph relations</option><option value="rrf">Hybrid search</option><option value="vector">Vector search</option><option value="lexical">Full-text search</option></select></label>{comparison&&<label className="comparison-check"><input type="checkbox" checked={includeComparison} onChange={event=>setIncludeComparison(event.target.checked)}/> Include the selected comparison and its query dates</label>}<button type="submit" className="primary-button" disabled={!available||pending||!question.trim()||status?.budget.remaining_calls===0}><Send size={16}/> Ask with evidence</button></div></form>
    <details className="limit-controls"><summary>Increase session limits</summary><p>Apply higher limits explicitly. Existing usage and reservations are kept.</p><label>New total call limit<input aria-label="New total call limit" type="number" min={status?.budget.max_calls??20} max={100000} value={limitCalls} onChange={event=>setLimitCalls(Number(event.target.value))}/></label><label>New total amount limit (USD)<input aria-label="New total amount limit USD" type="number" min={status?.budget.max_amount??0} step="0.01" value={limitAmount} onChange={event=>setLimitAmount(event.target.value)}/></label><button type="button" className="outline-button" onClick={()=>void request('/api/ai/limits',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_calls:limitCalls,max_amount_usd:limitAmount})}).then(()=>refreshStatus()).catch(reason=>setError(reason.message))}>Apply higher limits</button></details>
    {pending&&<p role="status">Preparing the scoped evidence and answer…</p>}{error&&<div role="alert" className="error-banner">{error}</div>}
    {result&&<article className="answer-card" data-testid="investigation-answer" data-snapshot-id={result.scope.snapshot_ids.join(',')}><div className="answer-heading"><BookOpen size={20}/><h3>{labels[result.answer.status]??result.answer.status}</h3></div>{result.answer.body&&<><span className="eyebrow">GENERATED EXPLANATION</span><p>{result.answer.body}</p></>}{result.answer.facts.length>0&&<div className="checked-facts"><strong>Facts checked against supplied source receipts</strong>{result.answer.facts.map((fact,index)=><div className="checked-fact" key={index}><span className="tag">{fact.kind}</span><FactValue fact={fact}/></div>)}</div>}
      {result.answer.citations.length>0&&<div className="answer-citations"><strong>Source evidence</strong>{result.answer.citations.map((id,index)=><button className="outline-button" onClick={()=>void openProof(id)} key={id}>Evidence {index+1} <span>{id.slice(0,10)}</span></button>)}</div>}{result.answer.limitations.length>0&&<ul className="answer-limits">{result.answer.limitations.map((value,index)=><li key={index}>{value}</li>)}</ul>}<footer>{result.answer.model_id??'No model called'} · {new Date(result.observed_at).toLocaleString()}<details><summary>Usage and request receipt</summary><pre>{JSON.stringify({request_id:result.answer.request_id,usage:result.answer.usage,supplied_evidence_ids:result.answer.supplied_evidence_ids},null,2)}</pre></details></footer></article>}
    {proof&&<div className="source-proof"><div className="answer-heading"><ShieldCheck size={19}/><h3>Original source field verified</h3><button className="text-button" onClick={()=>setProof(undefined)}>Close</button></div><p>{proof.chunk.pointer} · characters {proof.chunk.start}–{proof.chunk.end}</p><pre>{proof.original_field_excerpt}</pre>{proof.source_observations.slice(0,1).map(value=><p className="proof-origin" key={value.digest}>{value.uri}<br/>SHA-256: {value.digest}<br/>Observed: {new Date(value.observed_at).toLocaleString()}</p>)}{proof.upstream_source_ids.length>0&&<details><summary>Upstream source receipts</summary><pre>{JSON.stringify({digests:proof.upstream_source_ids,pointer:proof.upstream_pointer},null,2)}</pre></details>}</div>}
    {jobId&&<JobProgress id={jobId} onDone={onDone}/>}
  </section>;
}
function FactValue({fact}:{fact:Fact}){
  const value=fact.value;
  if(fact.kind==='count')return <span>{String(value.metric).replaceAll('_',' ')}: <strong>{String(value.count)}</strong></span>;
  if(fact.kind==='version')return <span>{String(value.package)} <strong>{String(value.version)}</strong></span>;
  if(fact.kind==='query')return <span>{String(value.package)} · {String(value.version)} · <strong>{String(value.status).replaceAll('_',' ')}</strong></span>;
  if(fact.kind==='comparison')return <span>{String(value.metric).replaceAll('_',' ')}: <strong>{String(value.value)}</strong></span>;
  return <pre>{JSON.stringify(value,null,2)}</pre>;
}
