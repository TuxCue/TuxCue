export type AudioSegment = {start_frame:number;end_frame:number};

export function frameCount(segments:AudioSegment[]) {
  return segments.reduce((total,segment)=>total+segment.end_frame-segment.start_frame,0);
}

export function removeFrames(segments:AudioSegment[],start:number,end:number):AudioSegment[] {
  const total=frameCount(segments);
  if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||start>=end||end>total||end-start===total) {
    throw new Error('Choose a section to remove and leave some audio in the clip.');
  }
  const result:AudioSegment[]=[];
  let position=0;
  for(const segment of segments) {
    const length=segment.end_frame-segment.start_frame;
    const before=Math.max(0,Math.min(length,start-position));
    const after=Math.max(0,Math.min(length,end-position));
    if(before>0)result.push({start_frame:segment.start_frame,end_frame:segment.start_frame+before});
    if(after<length)result.push({start_frame:segment.start_frame+after,end_frame:segment.end_frame});
    position+=length;
  }
  return result;
}
