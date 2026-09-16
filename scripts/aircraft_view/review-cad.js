import * as THREE from '../three.module.js';
import { OrbitControls } from '../OrbitControls.js';

function parseSTL(b64) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const view = new DataView(bytes.buffer), count = view.getUint32(80, true);
  const position = new Float32Array(count * 9);
  for (let i = 0, offset = 84, p = 0; i < count; i++) {
    offset += 12;
    for (let j = 0; j < 9; j++, offset += 4) position[p++] = view.getFloat32(offset, true);
    offset += 2;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
  geometry.applyMatrix4(new THREE.Matrix4().set(1,0,0,0, 0,0,1,0, 0,1,0,0, 0,0,0,1));
  geometry.computeVertexNormals();
  return geometry;
}

export function createCAD(host, config) {
  const data = config.payload, d = data.dims;
  host.innerHTML = `<div class="cad-canvas" aria-label="Interactive aircraft CAD"></div>
    <div class="cad-toolbar"><div class="segmented" aria-label="Camera view">
      ${['Iso','Top','Side','Front'].map(v => `<button data-camera="${v.toLowerCase()}" aria-pressed="${v === 'Iso'}">${v}</button>`).join('')}</div>
      <button class="icon-button" data-fit title="Fit aircraft" aria-label="Fit aircraft"><i data-lucide="maximize"></i></button>
      <button class="icon-button" data-settings title="CAD layers" aria-label="CAD layers" aria-expanded="false"><i data-lucide="layers"></i></button></div>
    <div class="cad-settings" hidden>
      ${[['structure','Airframe'],['cells','Solar array'],['parts','Equipment'],['grid','Reference grid'],['dims','Span dimension']].map(([id,label]) => `<label>${label}<input data-layer="${id}" type="checkbox" checked></label>`).join('')}
      <label>Airframe opacity <output id="opacity-value">85%</output></label><input data-opacity type="range" min="15" max="100" value="85" aria-label="Airframe opacity">
    </div><div class="cad-label">${d.span_m.toFixed(3)} m SPAN<br>OPTIMIZED GEOMETRY</div>
    <div class="cad-legend"><span><i class="dot" style="background:#3378aa"></i>Solar</span><span><i class="dot" style="background:#6da586"></i>Battery</span><span><i class="dot" style="background:#c47c32"></i>Propulsion</span></div>`;
  const stage = host.querySelector('.cad-canvas');
  let renderer;
  try { renderer = new THREE.WebGLRenderer({antialias:true, alpha:true, preserveDrawingBuffer:true}); }
  catch { stage.innerHTML = '<div class="loader">3D unavailable: WebGL is required.</div>'; return {dispose(){}}; }
  renderer.setClearColor(0,0);
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  stage.appendChild(renderer.domElement);
  const scene = new THREE.Scene(), aircraft = new THREE.Group();
  scene.add(aircraft);
  const camera = new THREE.PerspectiveCamera(38,1,.01,100);
  const orbit = new OrbitControls(camera,renderer.domElement);
  orbit.enableDamping = true;
  orbit.minDistance = 1;
  orbit.maxDistance = 30;
  scene.add(new THREE.AmbientLight(0xffffff,1.2));
  const light = new THREE.DirectionalLight(0xffffff,1.4);
  light.position.set(-3,8,4);scene.add(light);
  const fill = new THREE.DirectionalLight(0xffffff,.65);fill.position.set(3,2,-4);scene.add(fill);
  const structMaterial = new THREE.MeshStandardMaterial({color:0xb4b9bc,metalness:.18,roughness:.65,transparent:true,opacity:.85,side:THREE.DoubleSide});
  const structure = new THREE.Mesh(parseSTL(config.struct),structMaterial);
  aircraft.add(structure);
  const cells = new THREE.Mesh(parseSTL(config.cells), new THREE.MeshStandardMaterial({color:0x3378aa,metalness:.2,roughness:.45,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2}));
  aircraft.add(cells);
  const props = new THREE.Mesh(parseSTL(config.props), new THREE.MeshStandardMaterial({color:0xc47c32,transparent:true,opacity:.48,side:THREE.DoubleSide}));
  aircraft.add(props);
  const parts = new THREE.Group();aircraft.add(parts);
  const colors = {battery:0x6da586,propulsion:0xc47c32,avionics:0xb58396};
  for (const p of Object.values(data.mass.positions)) {
    if (!p.draggable) continue;
    const size = p.size;
    const geometry = p.kind === 'sphere' ? new THREE.SphereGeometry(size[0],16,12) : new THREE.BoxGeometry(size[0],size[2] || .03,size[1] || .03);
    const mesh = new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:colors[p.category] || 0x999999,roughness:.6}));
    mesh.position.set(p.xyz[0],p.xyz[2],p.xyz[1]);parts.add(mesh);
  }
  const bounds = new THREE.Box3().setFromObject(aircraft);
  const center = bounds.getCenter(new THREE.Vector3());
  const grid = new THREE.GridHelper(10,40,0xc5c7c9,0xe0e2e4);
  grid.position.set(center.x,bounds.min.y-.12,0);scene.add(grid);
  const dims = new THREE.Group();scene.add(dims);
  const dimX = -.22;
  const dimPoints = [[dimX,.02,-d.span_m/2],[dimX,.02,d.span_m/2]];
  const dimMat = new THREE.LineBasicMaterial({color:0x878e94,transparent:true,opacity:.65});
  dims.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(dimPoints.map(p => new THREE.Vector3(...p))),dimMat));
  for (const z of [-d.span_m/2,d.span_m/2]) dims.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(dimX-.06,.02,z),new THREE.Vector3(dimX+.06,.02,z)]),dimMat));
  const directions = {iso:[-3.5,5.5,1.7],top:[0,1,.0001],side:[0,.03,1],front:[-1,.04,0]};
  let activeView = 'iso';
  function fit(name = activeView) {
    activeView = name;
    const dir = new THREE.Vector3(...directions[name]).normalize();
    const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),dir).normalize();
    const up = new THREE.Vector3().crossVectors(dir,right).normalize();
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov/2)), tanH = tanV*camera.aspect;
    let distance = 1;
    for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) for (const z of [bounds.min.z,bounds.max.z]) {
      const p = new THREE.Vector3(x,y,z).sub(center);
      distance = Math.max(distance, Math.abs(p.dot(right))/tanH + p.dot(dir), Math.abs(p.dot(up))/tanV + p.dot(dir));
    }
    camera.position.copy(center).addScaledVector(dir,distance*1.15);
    orbit.target.copy(center);orbit.update();
    host.querySelectorAll('[data-camera]').forEach(b => b.setAttribute('aria-pressed',String(b.dataset.camera === name)));
  }
  function resize() {
    const w = stage.clientWidth,h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();fit();
  }
  function paint() {
    const dark = document.documentElement.dataset.theme === 'dark';
    const materials=Array.isArray(grid.material)?grid.material:[grid.material];
    materials.forEach(m=>{m.color.setHex(dark?0x777777:0xffffff);m.transparent=true;m.opacity=dark?.4:.7;});
    structMaterial.color.setHex(dark ? 0xd8dcdf:0xb4b9bc);
  }
  host.querySelectorAll('[data-camera]').forEach(b => b.onclick = () => fit(b.dataset.camera));
  host.querySelector('[data-fit]').onclick = () => fit();
  const settings = host.querySelector('.cad-settings'),toggle=host.querySelector('[data-settings]');
  toggle.onclick = () => {settings.hidden=!settings.hidden;toggle.setAttribute('aria-expanded',String(!settings.hidden));};
  const layers = {structure,cells,parts,grid,dims};
  host.querySelectorAll('[data-layer]').forEach(c => c.onchange = () => {layers[c.dataset.layer].visible=c.checked;if(c.dataset.layer==='parts')props.visible=c.checked;});
  host.querySelector('[data-opacity]').oninput = e => {structMaterial.opacity=Number(e.target.value)/100;host.querySelector('output').textContent=e.target.value+'%';};
  const observer=new ResizeObserver(resize);observer.observe(stage);
  document.addEventListener('review-theme',paint);paint();resize();
  let frame;
  function tick(){orbit.update();renderer.render(scene,camera);frame=requestAnimationFrame(tick);}
  tick();
  return {dispose(){cancelAnimationFrame(frame);observer.disconnect();document.removeEventListener('review-theme',paint);orbit.dispose();scene.traverse(o=>{o.geometry?.dispose();const mats=o.material?(Array.isArray(o.material)?o.material:[o.material]):[];mats.forEach(m=>m.dispose());});renderer.dispose();renderer.forceContextLoss();host.innerHTML='';}};
}
