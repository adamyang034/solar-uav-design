// Definitions use the model's actual conventions, not generic CAD terminology.
const definitions = new Map();
const normalize = text => text.trim().toLowerCase();
function add(names, text, formula='') {
  for (const name of names.split('|')) definitions.set(normalize(name), {text,formula});
}
add('Boom length|boom_length_m', 'Longitudinal distance from the wing leading edge to the vertical-tail root leading edge. Uses the fin root, not the swept tip. This reporting datum is separate from the physical tube length used for mass and drag.', 'L_boom = x_LE,vertical-tail - x_LE,wing');
add('Modeled tube length|boom_tube_length_m|Booms', 'Material length of each modeled tube, used for tube mass, drag and inertia. Tube attachments have not moved when the boom reporting datum changes. Historical optimizer CSV boom_length_m columns use this tube-length convention.', 'm_booms = number of tubes * tube length * linear mass');
add('Span|Wingspan|span_m|WINGSPAN_MAX_M', 'Full wingtip-to-wingtip span, including the center panel. Not a half-span or one outboard panel.');
add('Root chord|chord_m', 'Leading-edge to trailing-edge distance of the constant-chord center wing, measured along the local chord line.');
add('Minimum rectangular chord|RECTANGULAR_MIN_CHORD_M', 'Minimum allowed constant wing chord for this rectangular study. This limit is enforced in the optimizer search bounds and exact feasibility checks; it is not applied to archived variants. Input values use meters; the requirement table uses millimeters.');
add('Tip chord', 'Local wing leading-edge to trailing-edge distance at the wingtip.', 'c_tip = taper ratio * root chord');
add('Root / tip chord', 'Root chord is the center-wing chord. Tip chord is the chord at the wingtip. Both are leading-edge to trailing-edge distances along the chord line.');
add('Area|Wing area', 'Projected planform area of the entire wing, including the center panel. This is not the upper-plus-lower wetted area.');
add('Aspect ratio', 'Full wing span squared divided by full wing planform area.', 'AR = b^2 / S');
add('Mean aerodynamic chord|mac_m', 'Area-weighted aerodynamic chord of the whole wing, used to normalize static margin and locate the assumed wing aerodynamic center.', 'MAC = integral(c(y)^2 dy) / S');
add('Taper ratio|taper_ratio', 'Tip chord divided by root chord. A value of 1 is rectangular; lower values have a smaller tip chord.', 'lambda = c_tip / c_root');
add('taper_start_frac', 'Fraction of each outboard panel from the wing joint to the tip that remains constant chord before taper starts. Not a fraction of the full span.');
add('Tip washout|washout_tip_deg', 'Reduction in wingtip incidence relative to the root. Positive washout means the tip is rotated nose-down; zero means no geometric twist.');
add('washout_start_frac', 'Start of the linear washout ramp, expressed as a fraction of each outboard panel measured from the wing joint.');
add('Whole-wing incidence', 'Trimmed wing-root incidence relative to the model aircraft x reference. Local incidence also subtracts the spanwise washout; this is not the flight angle of attack.');
add('H-stab trim incidence|incidence_hstab_deg', 'Calculated fixed horizontal-stabilizer mounting angle relative to the aircraft reference axis, intended to trim at the model night-cruise design point with approximately neutral elevator. Negative means leading edge down. Accounts for wing pitching moment and estimated downwash with the assumed quarter-chord CG. This is not elevator deflection or local tail angle of attack; other speeds or CG positions may require elevator trim. Preliminary model setting, not flight-validated.');
add('Airfoil', 'Airfoil section used by the wing aerodynamic and surface-geometry models.');
add('Horizontal tail airfoil', 'Airfoil section used for the horizontal stabilizer, including its neutral elevator profile. Applies to both stabilizers on split-empennage designs.');
add('Vertical tail airfoil', 'Airfoil section used for each vertical stabilizer, including the neutral rudder profile where fitted.');
add('Horizontal tail span', 'Tip-to-tip span of one horizontal stabilizer. The split configuration has two independent stabilizers; this value is per stabilizer.');
add('Horizontal tail chord', 'Leading-edge to trailing-edge chord of a horizontal stabilizer, including its elevator region.');
add('Horizontal tail arm|tail_arm_m', 'Longitudinal distance from the assumed wing aerodynamic center at quarter mean aerodynamic chord to the horizontal-tail quarter-chord aerodynamic center. Not a leading-edge separation.', 'l_h = x_AC,horizontal-tail - x_AC,wing');
add('Wing LE to H-stab LE', 'Longitudinal distance from the wing leading edge to the horizontal-stabilizer root leading edge, positive aft along the aircraft x axis. This is not the quarter-chord horizontal tail arm, the vertical-tail boom datum, or the tube material length. Uses the model leading-edge coordinates, not a slanted three-dimensional distance.', 'L = x_LE,horizontal-tail - x_LE,wing');
add('Vertical tail height', 'Full height of one vertical fin. For the straddling pi-tail this includes the portions above and below the wing plane.');
add('Vertical tail chord', 'Leading-edge to trailing-edge chord of one fin. Current fins have constant chord, including when swept.');
add('Vertical tail arm|vstab_arm_m', 'Longitudinal distance from the wing quarter-MAC aerodynamic center to the vertical-tail aerodynamic center. Fin sweep can increase this arm without moving the fin root.', 'l_v = x_AC,vertical-tail - x_AC,wing');
add('Aileron span / side', 'Spanwise length of one aileron, from its automatically sized inboard end to the tip keep-out boundary. Not the sum of left and right ailerons.');
add('Boom OD', 'Outside diameter of the modeled circular boom tube. This does not specify wall thickness, material properties or structural approval.');
add('Boom tube|BOOM_PART_NUMBER', 'Selected supplier part for this configuration only. Its recorded physical properties are applied before recomputing mass, drag and performance. Selection does not establish structural qualification.');
add('Boom linear mass|BOOM_MASS_PER_M', 'Nominal tube mass per metre, multiplied by the modeled material length. Excludes separate attachment, servo and wiring budgets.', 'm_tubes = number of tubes * material length * linear mass');
add('Boom ID|BOOM_INNER_DIAMETER_M', 'Inside diameter of the selected tube in the stated units. For a circular tube, wall thickness is half the difference between outside and inside diameters.');
add('BOOM_DIAMETER_M', 'Outside diameter of the boom in metres, used by both the parasite drag model and CAD mesh.');
add('BOOM_AXIAL_MODULUS_PA', 'Nominal supplier axial laminate modulus in pascals. Recorded for hardware traceability; the mission model does not calculate structural vibration or strength from this property.');
add('boom_spacing_m', 'Distance between the two wing joints that bound the constant-chord center panel. For twin-fuselage layouts this is also boom/fuselage centerline spacing; for conventional layouts it is not a fuselage width.');
add('Fuselage length', 'Longitudinal distance from the propeller disk plane to the wing trailing edge. The current pod geometry and wetted-area model use this convention.', 'L_fuselage = propeller-to-wing-LE offset + root chord');
add('Propeller diameter', 'Tip-to-tip diameter of one propeller disk, not its radius. Catalog diameter is reported in inches.');
add('Propeller|Propulsion', 'Selected real catalog propeller or installed propulsion combination. Diameter and pitch are not a continuously fabricated propeller; the optimizer verifies catalog hardware.');
add('Motors', 'Number of installed motors, with the selected motor model when shown. Conventional uses one; twin-fuselage configurations use two.');
add('Yaw control|Active yaw authority', 'Conventional layouts use the rudder; twin-fuselage layouts use differential thrust. Passing this authority check does not establish passive yaw or spiral stability.');
add('Rudder chord · installed / required', 'Installed rudder chord and the minimum chord predicted by the model to meet its yaw-rate and sideslip-trim requirements. Both are per rudder.');
add('Rudder moment · available / required', 'Available rudder yawing moment and the required sideslip-trim moment at the evaluated control speed. This is a modeled authority comparison, not a structural torque rating.');
add('Morning SOC|Search morning SOC|Recomputed morning SOC', 'The lower of current and next morning battery SOC at the onset of net charging in the scored cycle. The optimizer maximizes this value while requiring next morning SOC not to decrease.', 'objective = min(SOC_current morning, SOC_next morning)');
add('Current morning', 'Battery SOC at the current morning transition into net charging in the scored cycle. The charging transition is not necessarily astronomical sunrise.');
add('Next morning', 'Battery SOC at the following morning net-charging transition. Must be at least the current morning SOC, apart from the stated numerical tolerance.');
add('Minimum scored SOC', 'Lowest battery SOC during the scored mission cycle, not the minimum of the separate 89-hour visualization.');
add('Energy reserve|Reserve', 'Battery energy remaining above the configured SOC floor at the lowest scored SOC. This is not daily surplus solar energy.', 'reserve_Wh = (minimum scored SOC - SOC floor) * nominal bank Wh');
add('Morning-to-morning recovery|Recovery ΔSOC', 'Next morning SOC minus current morning SOC. Recovery is evaluated at corresponding net-charging transitions. Values labeled pp are percentage-point differences, not relative percentages.', 'delta_SOC = next morning SOC - current morning SOC');
add('Reserve condition|SOC_MIN', 'Minimum allowed battery SOC is the configured floor. The displayed minimum is the lowest SOC in the scored cycle, which must remain at or above this floor.');
add('Night bus power|Day bus power', 'Total modeled electrical bus demand at the optimized night/day operating point, including propulsion demand and avionics. Not shaft power or aerodynamic power.');
add('Night airspeed|v_cruise_ms', 'Evaluated cruise true airspeed relative to the surrounding air, not ground speed. Night operating speed includes the model wind/stall floors and power optimization.');
add('Stall airspeed', 'Modeled unbanked stall airspeed for the current mass and aerodynamic assumptions. Not the higher cruise or loiter stall-margin speed.');
add('Lift / drag|Night lift / drag', 'Aircraft weight supported divided by total modeled aerodynamic drag at the evaluated night operating point.', 'L/D = weight / total drag');
add('Climb rate|CLIMB_RATE_REQ_MS', 'Predicted vertical climb rate from the propulsion and aircraft model at the checked operating point. This is not verified flight performance.');
add('Static margin|STATIC_MARGIN_MIN', 'Longitudinal static stability margin normalized by wing mean aerodynamic chord. The model assumes CG at wing quarter-MAC, not the illustrative CAD component CG.', 'SM = (x_neutral point - x_CG) / MAC');
add('Roll rate|ROLL_RATE_MIN_DEG_S', 'Modeled steady roll rate at the configured control deflection and evaluated control speed. Not roll acceleration or bank angle.');
add('Takeoff mass|Total modeled mass|Aircraft model', 'Sum of the current aircraft structural estimates, installed hardware and fixed mass budgets. This is a modeled takeoff mass, not an as-built weighing.');
add('Maximum takeoff mass|Takeoff mass limit|MTOW_MAX_KG', 'Maximum permitted modeled takeoff mass. Mass headroom is this limit minus the calculated aircraft mass.');
add('Mass headroom', 'Remaining mass allowance in kg or g, not a factor of safety.', 'mass headroom = takeoff mass limit - modeled takeoff mass');
add('Battery fraction', 'Installed battery mass divided by total modeled aircraft mass. Excludes MPPTs, wiring and power boards.', 'battery fraction = battery mass / total mass');
add('Battery energy|Nominal battery energy|Nominal bank energy', 'Sum of nominal pack energy across the installed packs. This includes energy below the usable SOC floor.', 'nominal bank Wh = number of packs * nominal Wh per pack');
add('Battery packs|Pack count', 'Integer count of installed battery packs. The battery option selects each pack type; the optimizer selects the pack count.');
add('Energy per pack|PACK_ENERGY_WH', 'Nominal stored energy of one selected battery pack, not the usable bank energy.');
add('Capacity per pack|PACK_CAPACITY_AH', 'Rated charge capacity of one pack in ampere-hours. This differs from stored energy in watt-hours.');
add('Usable energy (80%)', 'Nominal battery energy between full charge and the 20% SOC floor. It is an energy-window value, not predicted endurance.', 'usable Wh = (1 - SOC floor) * nominal bank Wh');
add('Charge current limit|PACK_CHARGE_MAX_A', 'Maximum modeled charging current per pack before the high-SOC taper; the bank limit scales with installed pack count.');
add('Modeled DCIR|PACK_R_INTERNAL_OHM', 'Assumed direct-current internal resistance of one battery pack, used in voltage and loss calculations.');
add('Solar cells|Solar array', 'Count of installed whole solar cells. The total can include tail cells when that layout permits them; it is not available empty packing capacity.');
add('Wing solar setback / minimum|Wing solar LE setback|Wing solar leading-edge setback', 'Actual foremost wing cell edge and/or the required chordwise setback from the local leading edge. The 40 mm keep-out plus half the cell-pitch gap places the first edge at 42.5 mm. Not a distance along the curved skin or a bend-radius certification.');
add('Wing LE keep-out|WING_SOLAR_LE_SETBACK_M', 'Minimum wing leading-edge exclusion measured chordwise before packing full cell-pitch footprints. The half-gap adds to the physical cell-edge clearance.');
add('Solar over ailerons|Solar cells over ailerons|SOLAR_ALLOW_AILERON_OVERLAP', 'Whether wing solar cells may overlap an aileron footprint. The GOLD comparison includes separate rectangular variants with and without this allowance. The tapered conventional design prohibits overlap; twin-boom designs retain their saved rules. When prohibited, the overlap-count requirement is zero and packing exclusion extends to the tip. When allowed, hinge clearance, wiring and moving-surface integration still require verification.');
add('String plan|Cells per string', 'Installed series-cell counts in each electrical string, listed longest first. Plus signs separate strings, not physical left-to-right locations. Each string has a modeled MPPT.');
add('Strings / MPPTs|MPPTs / strings|MPPT controllers', 'Number of independent installed solar strings and MPPT controllers. The current model assigns one controller per string.');
add('MPPT topology', 'Assumed buck/boost solar power conversion. This proposed hardware model can convert both above and below battery voltage and remains provisional.');
add('MPPT mass|MPPT_MASS_KG', 'Mass of one proposed MPPT controller, multiplied by the number of installed strings for total controller mass.');
add('MPPT efficiency|MPPT_EFFICIENCY', 'Assumed fraction of accepted solar input power delivered through the controller before other separately modeled losses.');
add('Max input current|MPPT_MAX_INPUT_A', 'Configured maximum PV input current per controller, not the aggregate battery charge-current limit.');
add('Solar / day|Solar energy / scored day', 'Modeled solar-bus energy available during the scored interval after modeled array/conversion losses. Some may be spilled by battery charging limits.');
add('Propulsion / day', 'Time-integrated electrical propulsion energy in the scored interval. Avionics energy is reported separately.');
add('Spill / day|Spilled energy / scored day', 'Solar energy that cannot be accepted or stored because of model battery/charging constraints. It cannot compensate for insufficient overnight storage.');
add('Night interval', 'Total modeled time when array supply is below propulsion plus avionics demand. It is a power-deficit interval, not astronomical sunset-to-sunrise duration.');
add('Avionics / day', 'Integrated fixed avionics bus demand over the scored interval, separate from propulsion demand.');
add('Unserved demand|Unserved energy', 'Electrical demand the modeled solar/battery system could not serve. The mission gate is strictly less than 0.5 Wh.');
add('Air density', 'Atmospheric density used at the evaluated cruise altitude and operating condition.');
add('Dynamic pressure', 'Aerodynamic pressure scale based on air density and true airspeed.', 'q = 0.5 * rho * V^2');
add('Net lift coefficient', 'Net aircraft lift coefficient referenced to the full wing planform area and dynamic pressure.', 'CL_net = weight / (q * S_wing)');
add('Wing-reference drag coefficient', 'Total modeled aircraft drag coefficient referenced to wing planform area, not just wing profile drag.', 'CD = total drag / (q * S_wing)');
add('Total drag', 'Sum of modeled aircraft aerodynamic drag contributions at the displayed operating point. Not propulsion electrical power.');
add('Aerodynamic power', 'Mechanical power required to overcome aerodynamic drag, before propeller and electrical-system losses.', 'P_aero = drag * true airspeed');
add('Wing Reynolds number', 'Wing Reynolds number based on mean aerodynamic chord and the evaluated airspeed and atmosphere.', 'Re = rho * V * MAC / dynamic viscosity');
add('CAD lump CG · x|CAD lump CG · y|CAD lump CG · z', 'Mass-weighted center of gravity of illustrative CAD component allocations. Aircraft axes are x aft from wing LE, y spanwise and z upward. These positions are not an as-built survey and do not replace the assumed quarter-chord aerodynamic CG.');
add('Ixx / Iyy / Izz', 'Illustrative mass moments of inertia about the reported component-allocation center of gravity: roll, pitch and yaw respectively, in kg m^2.');
add('Headroom', 'Signed dimensional allowance: calculated minus a minimum, or maximum minus calculated. Positive is within the limit. This is not a structural factor-of-safety margin.', 'minimum gate: actual - limit; maximum gate: limit - actual');
add('Limit', 'Requirement threshold or bound, with its inequality. Numerical tolerance is separate and does not alter the displayed actual value.');
add('Calculated', 'Value calculated for the selected aircraft. Display rounding does not control pass/fail.');
add('Aircraft share|Aircraft %', 'Component or portion mass divided by total modeled aircraft mass.', 'share = item mass / aircraft mass');
add('Portion %', 'Component mass divided by its parent portion mass. Different denominator from Aircraft %.');
add('Residual', 'Allocated mass minus the aircraft model total. Values near machine precision indicate the hierarchy reconciles, not an unallocated mass allowance.');
add('Model feasibility|All geometry & design gates', 'Pass means the selected aircraft satisfies the implemented model gates. Structural strength, buckling, flutter, control reversal and flight qualification are not established.');
add('Search method', 'Surrogate-assisted AeroSandbox/IPOPT search followed by exact evaluation of actual catalog hardware and integer packing. Not proof of a global optimum.');
add('Calculation method', 'Method that produced the recorded result. A fixed-design hardware reevaluation retains the parent geometry and propulsion choices, applies the selected component, and reruns the original performance model. It is not a new optimization.');
add('Recorded morning SOC', 'Morning SOC stored in the source result CSV under the recorded hardware and model assumptions. Compared with the independently rebuilt mission result for reproducibility.');
add('Search seed', 'Random-number seed recorded for repeatable sampling with the same code, data and search settings.');
add('Exact evaluations', 'Original-model candidate evaluations, including recorded cross-battery and containing-design-space checks. Not the number of fitted surrogate predictions.');
add('Retained / passing candidates', 'Number of retained evaluated CSV rows and how many satisfy the mission closure flag. This can be smaller than total attempted exact evaluations.');
add('Difference', 'Recomputed morning SOC minus saved result morning SOC, in percentage points. This is a reproducibility check, not measurement error.');
add('Solar packing & electrical limits', 'Combined geometric cell packing, actual string sizes and configured controller electrical-limit checks.');
add('Stability & control gates', 'The implemented static-margin, elevator, pitch and roll requirements for the current design. Passive directional-stability thresholds may be disabled.');
add('Strength, buckling & aeroelasticity', 'Outside this optimizer study. No structural, flutter or control-reversal approval is implied by an otherwise model-feasible aircraft.');
add('Rudder authority|Differential-thrust authority', 'The implemented yaw-authority check at the evaluated control speed, using the layout-specific actuator.');

const inputs = {
  SOLSTICE_DATE:'Clear-sky design day used to score the repeating morning cycle.',
  LATITUDE_DEG:'Mission-site latitude in degrees, north positive.',
  LONGITUDE_DEG:'Mission-site longitude in degrees, east positive.',
  SITE_ALTITUDE_M:'Mission-site ground elevation above mean sea level.',
  CRUISE_ALT_AGL_M:'Cruise height above the site ground, not mean sea level.',
  YAW_RATE_MIN_DEG_S:'Minimum modeled steady yaw-rate authority requirement.',
  REQUIRE_YAW_STABILITY:'Whether passive directional-stability thresholds are enforced. Yaw actuator authority is checked separately.',
  PACK_MASS_KG:'Installed modeled mass of one battery pack.',
  MPPT_MAX_PV_VOC_V:'Configured open-circuit PV string-voltage design limit per MPPT.',
  MPPT_MAX_PV_ABS_V:'Absolute PV input-voltage limit for the proposed MPPT.',
  MPPT_MAX_PANEL_W:'Configured maximum panel/string power per MPPT.',
  PROP_THRUST_DERATE:'Multiplier reducing catalog propeller thrust for the model uncertainty allowance.',
  PROP_POWER_INFLATE:'Multiplier increasing catalog propeller power demand for the model uncertainty allowance.',
  ESC_EFFICIENCY:'Assumed motor-controller electrical efficiency.',
  GEARBOX_EFFICIENCY:'Gearbox efficiency used only where the selected drive model includes a gearbox; not evidence that the selected direct drive has one.',
  CELL_BIN_DEFAULT:'Selected solar-cell performance bin for the electrical model.',
  CELL_MASS_KG:'Mass of one solar cell, excluding its separately modeled interconnect allowance.',
  ENCAPSULATION_TRANSMISSION:'Fraction of incident light transmitted through the modeled encapsulation.',
  WIRING_MISMATCH_SOILING_EFF:'Combined configured power multiplier for wiring, cell mismatch and soiling losses.',
  CELL_PITCH_M:'Cell-to-cell packing pitch, including cell size plus spacing. This defines reserved footprints.',
  CELL_SIDE_M:'Physical side length of one square solar cell, excluding packing gaps.',
  WING_TOP_USABLE_CHORD_FRAC:'Fraction of local wing chord considered usable before leading-edge and control-surface exclusions.',
  AILERON_CHORD_FRAC:'Fraction of local wing chord aft of the aileron hinge.',
  AILERON_TIP_KEEP_OUT_M:'Spanwise distance from wingtip to the outer aileron boundary.',
  elevator_frac:'Elevator chord divided by horizontal-tail chord.',
  hstab_ar:'Horizontal-stabilizer aspect ratio used by the geometry model.',
  vstab_ar:'Aspect ratio of one vertical fin used by the geometry model.',
  aileron_chord_frac:'Aileron chord divided by local wing chord.'
};
for (const [name,text] of Object.entries(inputs)) add(name,text);

export function definitionFor(label, payload) {
  const key = normalize(label);
  const item = definitions.get(key);
  if (!item) return null;
  if (key === 'boom length' || key === 'boom_length_m') {
    const d = payload?.dimension_definitions?.boom_length_m;
    return d ? {...item, formula:`Selected configuration:\n${d.end_x_m.toFixed(4)} m - ${d.start_x_m.toFixed(4)} m = ${(d.end_x_m-d.start_x_m).toFixed(4)} m`} : item;
  }
  if (key === 'modeled tube length' || key === 'boom_tube_length_m') {
    const d = payload?.dimension_definitions?.boom_tube_length_m;
    return d ? {...item, formula:`Selected tube endpoints:\nx = ${d.start_x_m.toFixed(4)} to ${d.end_x_m.toFixed(4)} m`} : item;
  }
  if ((key === 'vertical tail arm' || key === 'vstab_arm_m') && payload?.combo?.layout_id === 'split') {
    return {text:'Not separately parameterized for the split T-tail. The fin and horizontal stabilizer share their leading-edge station; the yaw model uses the horizontal-tail arm. A blank value does not mean zero length.'};
  }
  return item;
}

export function definedLabel(label, payload, override=null) {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const definition = override || definitionFor(label,payload);
  if (!definition) return `<span class="variable-label"><span class="variable-name">${escape(label)}</span></span>`;
  return `<span class="variable-label"><span class="variable-name">${escape(label)}</span><button type="button" class="definition-button" aria-label="Definition: ${escape(label)}" data-definition-title="${escape(label)}" data-definition-text="${escape(definition.text)}" data-definition-formula="${escape(definition.formula)}"><i data-lucide="info" aria-hidden="true"></i></button></span>`;
}
