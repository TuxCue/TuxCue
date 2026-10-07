import test from 'node:test';
import assert from 'node:assert/strict';
import {frameCount,removeFrames} from '../src/audioEdits.ts';
const segment=(start_frame,end_frame)=>({start_frame,end_frame});

test('successive cuts use the shortened timeline and do not change prior plans',()=>{
  const original=[segment(0,1000)];
  const first=removeFrames(original,200,400);
  assert.deepEqual(first,[segment(0,200),segment(400,1000)]);
  const second=removeFrames(first,300,500);
  assert.deepEqual(second,[segment(0,200),segment(400,500),segment(700,1000)]);
  assert.equal(frameCount(second),600);
  assert.deepEqual(original,[segment(0,1000)]);
  assert.deepEqual(first,[segment(0,200),segment(400,1000)]);
});
test('cuts crossing an earlier join retain both outer ends',()=>{
  assert.deepEqual(removeFrames([segment(0,200),segment(400,1000)],100,400),
    [segment(0,100),segment(600,1000)]);
});
test('beginning and ending cuts have no empty sections',()=>{
  assert.deepEqual(removeFrames([segment(0,200),segment(400,1000)],0,200),[segment(400,1000)]);
  assert.deepEqual(removeFrames([segment(0,200),segment(400,1000)],200,800),[segment(0,200)]);
});
test('empty, reversed, fractional, and out-of-range cuts are rejected',()=>{
  for(const [start,end] of [[0,1000],[100,100],[200,100],[-1,10],[0,1001],[1.5,20]]){
    assert.throws(()=>removeFrames([segment(0,1000)],start,end));
  }
});
