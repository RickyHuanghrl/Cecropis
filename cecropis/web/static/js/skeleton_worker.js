/* Decode display caches off the UI thread. IDs never pass through float32. */
self.onmessage = ({data}) => {
  const {token, kind, buffer} = data;
  try {
    const view = new DataView(buffer);
    if (buffer.byteLength < 8) throw Error('header');
    const n = view.getUint32(0, true), e = view.getUint32(4, true);
    if (kind === 'background') {
      if (e !== 0 || buffer.byteLength !== 8 + n * 32) throw Error('background_length');
      const points = new Float32Array(buffer, 8, n * 6);
      const ids = new Array(n);
      for (let i=0; i<n; i++) ids[i] = view.getBigUint64(8+n*24+i*8, true).toString();
      self.postMessage({token,kind,points,ids}, [buffer]);
    } else {
      if (buffer.byteLength !== 8+n*16+e*8 || n>4000000 || e>8000000) throw Error('geometry_length');
      const points = new Float32Array(buffer, 8, n*3);
      const radii = new Float32Array(buffer, 8+n*12, n);
      const edges = new Uint32Array(buffer, 8+n*16, e*2);
      for (let i=0; i<edges.length; i++) if (edges[i]>=n) throw Error('edge_index');
      self.postMessage({token,kind,points,radii,edges}, [buffer]);
    }
  } catch(error) { self.postMessage({token,error_code:['header','background_length','geometry_length','edge_index'].includes(error.message) ? error.message : 'decode',error:error.message}); }
};
