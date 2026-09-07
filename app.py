import math
import re

import matplotlib.pyplot as plt
import streamlit as st


# ============================================================
# Page setting
# ============================================================
st.set_page_config(
    page_title="Spectre Input Waveform Generator",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1100px;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Spectre Input Waveform Generator")
st.caption("Simulator input waveform checker / Spectre vsource generator")


# ============================================================
# Engineering notation
# ============================================================
SCALE = {
    "": 1.0,
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "meg": 1e6,
    "M": 1e6,
    "g": 1e9,
    "G": 1e9,
}


def parse_eng(value):
    value = str(value).strip()
    pattern = (
        r"^"
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
        r"([a-zA-Z]*)"
        r"$"
    )
    match = re.match(pattern, value)
    if not match:
        raise ValueError(f"Invalid value: {value}")

    number = float(match.group(1))
    suffix = match.group(2)
    if suffix not in SCALE:
        raise ValueError(f"Unknown suffix: {suffix}")
    return number * SCALE[suffix]


def format_value(value):
    if abs(value) < 1e-30:
        return "0"
    return f"{value:.12g}"


# ============================================================
# Common helpers
# ============================================================
def get_delay(net):
    text = str(net.get("delay", "0")).strip() or "0"
    delay = parse_eng(text)
    if delay < 0:
        raise ValueError("Delay must be >= 0.")
    return delay


def source_name(net_name):
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", net_name)
    if not safe_name:
        safe_name = "net"
    return "_v_" + safe_name


def target_name(cell_name, net_name):
    if cell_name.strip():
        return f"{cell_name.strip()}.{net_name}"
    return net_name


# ============================================================
# PWL
# ============================================================
def parse_waveform(text):
    tokens = text.split()
    if not tokens:
        raise ValueError("Waveform is empty.")
    if len(tokens) % 2 != 0:
        raise ValueError("Waveform must be: 'time1 voltage1 time2 voltage2 ...'")

    times = []
    voltages = []
    for i in range(0, len(tokens), 2):
        times.append(parse_eng(tokens[i]))
        voltages.append(parse_eng(tokens[i + 1]))

    for i in range(1, len(times)):
        if times[i] < times[i - 1]:
            raise ValueError("Time must be monotonically increasing.")
    return times, voltages


def points_to_pwl(times, voltages):
    result = []
    for t, v in zip(times, voltages):
        result.append(format_value(t))
        result.append(format_value(v))
    return " ".join(result)


# ============================================================
# Preview waveform generators
# ============================================================
def preview_dc(net):
    value = parse_eng(net["dc"])
    # A short, flat segment for plotting. Actual x-limit is set later.
    return [0.0, 1.0], [value, value]


def preview_pulse(net):
    vlow = parse_eng(net["vlow"])
    vhigh = parse_eng(net["vhigh"])
    rise = parse_eng(net["rise"])
    width = parse_eng(net["width"])
    fall = parse_eng(net["fall"])

    if rise < 0 or width < 0 or fall < 0:
        raise ValueError("Rise / Width / Fall must be >= 0.")

    times = [0.0, rise, rise + width, rise + width + fall]
    voltages = [vlow, vhigh, vhigh, vlow]
    return times, voltages


def preview_clock(net):
    vlow = parse_eng(net["vlow"])
    vhigh = parse_eng(net["vhigh"])
    rise = parse_eng(net["rise"])
    width = parse_eng(net["width"])
    fall = parse_eng(net["fall"])
    period = parse_eng(net["period"])
    cycles = int(net["preview_cycles"])

    if period <= 0:
        raise ValueError("Period must be > 0.")
    if rise < 0 or width < 0 or fall < 0:
        raise ValueError("Rise / Width / Fall must be >= 0.")
    if rise + width + fall > period:
        raise ValueError("Rise + Width + Fall must be <= Period.")
    if cycles < 1:
        raise ValueError("Preview cycles must be >= 1.")

    times = []
    volts = []
    for cycle in range(cycles):
        t0 = cycle * period
        points = [
            (t0, vlow),
            (t0 + rise, vhigh),
            (t0 + rise + width, vhigh),
            (t0 + rise + width + fall, vlow),
            (t0 + period, vlow),
        ]
        for t, v in points:
            if times and abs(t - times[-1]) < 1e-30 and v == volts[-1]:
                continue
            times.append(t)
            volts.append(v)
    return times, volts


def preview_sine(net):
    dc = parse_eng(net["sinedc"])
    ampl = parse_eng(net["ampl"])
    freq = parse_eng(net["freq"])
    phase_deg = float(net["sinephase"])
    cycles = int(net["sine_preview_cycles"])

    if freq <= 0:
        raise ValueError("Sine frequency must be > 0.")
    if cycles < 1:
        raise ValueError("Preview cycles must be >= 1.")

    period = 1.0 / freq
    samples = max(200, cycles * 100)
    phase = math.radians(phase_deg)
    times = [period * cycles * i / (samples - 1) for i in range(samples)]
    volts = [dc + ampl * math.sin(2.0 * math.pi * freq * t + phase) for t in times]
    return times, volts


def normalize_bit_data(data):
    compact = re.sub(r"[\s_]+", "", str(data))
    if not compact:
        raise ValueError("Bit data is empty.")
    if not re.fullmatch(r"[01mzMZ]+", compact):
        raise ValueError("Bit data can contain only 0, 1, m, z.")
    return compact.lower()


def bit_state_voltage(state, vlow, vhigh, last_voltage):
    if state == "0":
        return vlow
    if state == "1":
        return vhigh
    # For preview only: m/z are shown at midpoint so they are visually obvious.
    # Spectre handles their actual source semantics.
    if state in ("m", "z"):
        return (vlow + vhigh) / 2.0
    return last_voltage


def preview_bit(net):
    vlow = parse_eng(net["vlow"])
    vhigh = parse_eng(net["vhigh"])
    bit_period = parse_eng(net["bit_period"])
    rise = parse_eng(net["rise"])
    fall = parse_eng(net["fall"])
    data = normalize_bit_data(net["bit_data"])
    rptstart = int(net["rptstart"])
    rpttimes = int(net["rpttimes"])

    if bit_period <= 0:
        raise ValueError("Bit period must be > 0.")
    if rise < 0 or fall < 0:
        raise ValueError("Rise / Fall must be >= 0.")
    if rise + fall > bit_period:
        raise ValueError("Rise + Fall must be <= Bit period.")
    if not (1 <= rptstart <= len(data)):
        raise ValueError(f"Repeat start must be 1 to {len(data)}.")

    # rpttimes < 0 means infinite in Spectre. Limit preview to a practical count.
    if rpttimes < 0:
        preview_repeat_count = int(net["bit_preview_repeats"])
    else:
        preview_repeat_count = rpttimes

    # Spectre plays the original data, then repeats data[rptstart-1:] rpttimes times.
    sequence = list(data)
    repeat_part = list(data[rptstart - 1 :])
    for _ in range(preview_repeat_count):
        sequence.extend(repeat_part)

    # Keep preview bounded even if a very large repeat count was entered.
    max_bits = 2000
    sequence = sequence[:max_bits]

    times = []
    volts = []
    current_v = bit_state_voltage(sequence[0], vlow, vhigh, vlow)
    times.append(0.0)
    volts.append(current_v)

    for i, state in enumerate(sequence):
        t0 = i * bit_period
        target_v = bit_state_voltage(state, vlow, vhigh, current_v)

        if i == 0:
            current_v = target_v
        elif target_v != current_v:
            transition_time = rise if target_v > current_v else fall
            times.append(t0)
            volts.append(current_v)
            times.append(t0 + transition_time)
            volts.append(target_v)
            current_v = target_v

        times.append((i + 1) * bit_period)
        volts.append(current_v)

    return times, volts


def get_preview_waveform(net):
    wave_type = net["wave_type"]
    if wave_type == "DC":
        return preview_dc(net)
    if wave_type == "PWL":
        return parse_waveform(net["waveform"])
    if wave_type == "Pulse":
        return preview_pulse(net)
    if wave_type == "Clock":
        return preview_clock(net)
    if wave_type == "Sine":
        return preview_sine(net)
    if wave_type == "Bit":
        return preview_bit(net)
    raise ValueError(f"Unknown waveform type: {wave_type}")


# ============================================================
# Spectre source generation
# ============================================================
def generate_source_line(cell_name, net):
    net_name = net["name"].strip()
    src = source_name(net_name)
    target = target_name(cell_name, net_name)
    wave_type = net["wave_type"]
    delay_text = str(net.get("delay", "0")).strip() or "0"

    # Validate delay for all transient waveform types.
    get_delay(net)

    if wave_type == "DC":
        parse_eng(net["dc"])
        return f"{src} ( {target} 0 ) vsource dc={net['dc'].strip()} type=dc"

    if wave_type == "PWL":
        times, volts = parse_waveform(net["waveform"])
        waveform = points_to_pwl(times, volts)
        return (
            f"{src} ( {target} 0 ) vsource "
            f"wave=[ {waveform} ] delay={delay_text} type=pwl"
        )

    if wave_type == "Pulse":
        preview_pulse(net)
        return (
            f"{src} ( {target} 0 ) vsource type=pulse "
            f"val0={net['vlow'].strip()} val1={net['vhigh'].strip()} "
            f"delay={delay_text} rise={net['rise'].strip()} "
            f"fall={net['fall'].strip()} width={net['width'].strip()}"
        )

    if wave_type == "Clock":
        preview_clock(net)
        return (
            f"{src} ( {target} 0 ) vsource type=pulse "
            f"val0={net['vlow'].strip()} val1={net['vhigh'].strip()} "
            f"delay={delay_text} period={net['period'].strip()} "
            f"rise={net['rise'].strip()} fall={net['fall'].strip()} "
            f"width={net['width'].strip()}"
        )

    if wave_type == "Sine":
        preview_sine(net)
        return (
            f"{src} ( {target} 0 ) vsource type=sine "
            f"sinedc={net['sinedc'].strip()} ampl={net['ampl'].strip()} "
            f"freq={net['freq'].strip()} sinephase={float(net['sinephase']):g} "
            f"delay={delay_text}"
        )

    if wave_type == "Bit":
        preview_bit(net)
        data = normalize_bit_data(net["bit_data"])
        return (
            f"{src} ( {target} 0 ) vsource type=bit "
            f"val0={net['vlow'].strip()} val1={net['vhigh'].strip()} "
            f"data=\"{data}\" period={net['bit_period'].strip()} "
            f"rise={net['rise'].strip()} fall={net['fall'].strip()} "
            f"delay={delay_text} rptstart={int(net['rptstart'])} "
            f"rpttimes={int(net['rpttimes'])}"
        )

    raise ValueError(f"Unknown waveform type: {wave_type}")


def generate_scs(cell_name, nets):
    lines = [
        "// ===============================================",
        "// Generated by Spectre Input Waveform Generator",
        "// ===============================================",
        "",
    ]

    for net in nets:
        if not net["name"].strip():
            continue
        try:
            lines.append(generate_source_line(cell_name, net))
        except Exception:
            continue

    lines.append("")
    return "\n".join(lines)


# ============================================================
# Default Net settings
# ============================================================
def create_default_net(net_id):
    return {
        "id": net_id,
        "name": "",
        "group": "",
        "wave_type": "PWL",
        "delay": "0",

        # DC
        "dc": "1.0",

        # PWL
        "waveform": "0 0 10u 0 10.1u 3.3",

        # Pulse / Clock / Bit common
        "vlow": "0",
        "vhigh": "3.3",
        "rise": "1n",
        "fall": "1n",

        # Pulse / Clock
        "width": "10u",
        "period": "20u",
        "preview_cycles": 5,

        # Sine
        "sinedc": "0",
        "ampl": "1",
        "freq": "1k",
        "sinephase": 0.0,
        "sine_preview_cycles": 3,

        # Bit
        "bit_data": "010",
        "bit_period": "1u",
        "rptstart": 2,
        "rpttimes": 5,
        "bit_preview_repeats": 10,
    }


# ============================================================
# Session state
# ============================================================
if "nets" not in st.session_state:
    st.session_state.nets = []
if "next_net_id" not in st.session_state:
    st.session_state.next_net_id = 0
if "show_wave" not in st.session_state:
    st.session_state.show_wave = False


# ============================================================
# Simulation setting
# ============================================================
st.subheader("Simulation setting")
cell_name = st.text_input(
    "sim bench cell name",
    value="",
    placeholder="Example: tb_adc",
    help="AMS simulation only. Leave blank for normal Spectre simulation.",
)

if cell_name:
    st.info(f"AMS mode : target net = `{cell_name}.net_name`")
else:
    st.info("Spectre mode : target net = `net_name`")

st.divider()


# ============================================================
# Add Net
# ============================================================
col_title, col_add = st.columns([6, 2])
with col_title:
    st.subheader("Input Nets")
with col_add:
    if st.button("➕ Add Net", use_container_width=True):
        net_id = st.session_state.next_net_id
        st.session_state.nets.append(create_default_net(net_id))
        st.session_state.next_net_id += 1
        st.rerun()


# ============================================================
# Net forms
# ============================================================
delete_id = None
wave_types = ["DC", "PWL", "Pulse", "Clock", "Sine", "Bit"]

for index, net in enumerate(st.session_state.nets):
    # Backward compatibility with session state created by an older app version.
    defaults = create_default_net(net.get("id", index))
    for key, value in defaults.items():
        net.setdefault(key, value)

    net_id = net["id"]
    with st.container(border=True):
        title_col, delete_col = st.columns([6, 2])
        with title_col:
            st.markdown(f"### Net {index + 1}")
        with delete_col:
            if st.button("🗑 Delete", key=f"delete_{net_id}", use_container_width=True):
                delete_id = net_id

        col1, col2, col3 = st.columns([2, 1.2, 1])
        with col1:
            net["name"] = st.text_input(
                "Net name",
                value=net["name"],
                key=f"net_name_{net_id}",
                placeholder="Example: vin",
            )
        with col2:
            net["group"] = st.text_input(
                "Viewer Group",
                value=net.get("group", ""),
                key=f"group_{net_id}",
                placeholder="blank = individual",
                help=(
                    "Waveforms with the same non-empty group name are drawn in the same card. "
                    "Leave blank to give this net its own card."
                ),
            )
        with col3:
            current_type = net["wave_type"] if net["wave_type"] in wave_types else "PWL"
            net["wave_type"] = st.selectbox(
                "Waveform Type",
                wave_types,
                index=wave_types.index(current_type),
                key=f"wave_type_{net_id}",
            )

        # -------------------- DC --------------------
        if net["wave_type"] == "DC":
            net["dc"] = st.text_input(
                "DC Voltage",
                value=net["dc"],
                key=f"dc_{net_id}",
                placeholder="1.8",
            )

        # -------------------- PWL -------------------
        elif net["wave_type"] == "PWL":
            net["waveform"] = st.text_input(
                "PWL waveform",
                value=net["waveform"],
                key=f"waveform_{net_id}",
                placeholder="0 1 10u 2.5 30u 1",
                help="time1 voltage1 time2 voltage2 ...",
            )

        # -------------------- Pulse -----------------
        elif net["wave_type"] == "Pulse":
            st.caption("One-shot pulse. Spectre type=pulse without period.")
            c1, c2 = st.columns(2)
            with c1:
                net["vlow"] = st.text_input("Initial / Low Voltage", value=net["vlow"], key=f"pulse_low_{net_id}")
            with c2:
                net["vhigh"] = st.text_input("High Voltage", value=net["vhigh"], key=f"pulse_high_{net_id}")
            c1, c2, c3 = st.columns(3)
            with c1:
                net["rise"] = st.text_input("Rise Time", value=net["rise"], key=f"pulse_rise_{net_id}")
            with c2:
                net["width"] = st.text_input("High Width", value=net["width"], key=f"pulse_width_{net_id}", help="Time held at val1 after the rising edge.")
            with c3:
                net["fall"] = st.text_input("Fall Time", value=net["fall"], key=f"pulse_fall_{net_id}")

        # -------------------- Clock -----------------
        elif net["wave_type"] == "Clock":
            st.caption("Continuous periodic pulse. Spectre type=pulse with period.")
            c1, c2 = st.columns(2)
            with c1:
                net["vlow"] = st.text_input("Low Voltage", value=net["vlow"], key=f"clock_low_{net_id}")
            with c2:
                net["vhigh"] = st.text_input("High Voltage", value=net["vhigh"], key=f"clock_high_{net_id}")
            c1, c2, c3 = st.columns(3)
            with c1:
                net["period"] = st.text_input("Period", value=net["period"], key=f"clock_period_{net_id}")
            with c2:
                net["width"] = st.text_input("High Width", value=net["width"], key=f"clock_width_{net_id}")
            with c3:
                net["preview_cycles"] = st.number_input("Preview Cycles", min_value=1, max_value=50, value=int(net["preview_cycles"]), step=1, key=f"clock_preview_cycles_{net_id}")
            c1, c2 = st.columns(2)
            with c1:
                net["rise"] = st.text_input("Rise Time", value=net["rise"], key=f"clock_rise_{net_id}")
            with c2:
                net["fall"] = st.text_input("Fall Time", value=net["fall"], key=f"clock_fall_{net_id}")

        # -------------------- Sine ------------------
        elif net["wave_type"] == "Sine":
            st.caption("Sinusoidal source. Spectre type=sine.")
            c1, c2 = st.columns(2)
            with c1:
                net["sinedc"] = st.text_input("DC Level", value=net["sinedc"], key=f"sinedc_{net_id}")
            with c2:
                net["ampl"] = st.text_input("Amplitude", value=net["ampl"], key=f"sine_ampl_{net_id}")
            c1, c2, c3 = st.columns(3)
            with c1:
                net["freq"] = st.text_input("Frequency", value=net["freq"], key=f"sine_freq_{net_id}", placeholder="1Meg")
            with c2:
                net["sinephase"] = st.number_input("Phase [deg]", value=float(net["sinephase"]), step=10.0, key=f"sine_phase_{net_id}")
            with c3:
                net["sine_preview_cycles"] = st.number_input("Preview Cycles", min_value=1, max_value=20, value=int(net["sine_preview_cycles"]), step=1, key=f"sine_preview_cycles_{net_id}")

        # -------------------- Bit -------------------
        elif net["wave_type"] == "Bit":
            st.caption("Digital bit pattern as an analog source. Repeat starts at rptstart and continues to the end of data.")
            c1, c2 = st.columns(2)
            with c1:
                net["vlow"] = st.text_input("Low Voltage (val0)", value=net["vlow"], key=f"bit_low_{net_id}")
            with c2:
                net["vhigh"] = st.text_input("High Voltage (val1)", value=net["vhigh"], key=f"bit_high_{net_id}")

            net["bit_data"] = st.text_input(
                "Bit Data",
                value=net["bit_data"],
                key=f"bit_data_{net_id}",
                placeholder="010",
                help='Example: data="010", rptstart=2 repeats the "10" portion.',
            )

            c1, c2, c3 = st.columns(3)
            with c1:
                net["bit_period"] = st.text_input("Bit Period", value=net["bit_period"], key=f"bit_period_{net_id}", help="Length of one bit, not the full repeated pattern.")
            with c2:
                net["rise"] = st.text_input("Rise Time", value=net["rise"], key=f"bit_rise_{net_id}")
            with c3:
                net["fall"] = st.text_input("Fall Time", value=net["fall"], key=f"bit_fall_{net_id}")

            c1, c2 = st.columns(2)
            with c1:
                net["rptstart"] = st.number_input("Repeat Start (rptstart)", min_value=1, value=int(net["rptstart"]), step=1, key=f"bit_rptstart_{net_id}")
            with c2:
                net["rpttimes"] = st.number_input("Repeat Times (rpttimes)", value=int(net["rpttimes"]), step=1, key=f"bit_rpttimes_{net_id}", help="Negative value = repeat forever in Spectre.")

            if int(net["rpttimes"]) < 0:
                net["bit_preview_repeats"] = st.number_input("Preview Repeats", min_value=1, max_value=100, value=int(net["bit_preview_repeats"]), step=1, key=f"bit_preview_repeats_{net_id}")

        # Delay is meaningful for transient waveform types, not DC.
        if net["wave_type"] != "DC":
            net["delay"] = st.text_input(
                "Delay",
                value=net["delay"],
                key=f"delay_{net_id}",
                placeholder="0",
                help="Spectre vsource delay parameter. Example: 10u",
            )

            if net["wave_type"] == "Bit":
                st.caption("During delay, Spectre holds the first state in data.")
            elif net["wave_type"] == "Sine":
                st.caption("During delay, Spectre holds the sine value at t = delay.")


# ============================================================
# Delete
# ============================================================
if delete_id is not None:
    st.session_state.nets = [net for net in st.session_state.nets if net["id"] != delete_id]
    st.rerun()

st.divider()


# ============================================================
# Validation
# ============================================================
errors = []
for net in st.session_state.nets:
    if not net["name"].strip():
        continue
    try:
        generate_source_line(cell_name, net)
    except Exception as e:
        errors.append(f'{net["name"]}: {e}')


# ============================================================
# Wave Check / Dump
# ============================================================
button_col1, button_col2 = st.columns(2)
with button_col1:
    if st.button("📈 Wave Check", type="primary", use_container_width=True):
        st.session_state.show_wave = True

scs_text = generate_scs(cell_name, st.session_state.nets)

with button_col2:
    st.download_button(
        "💾 .scs Dump",
        data=scs_text,
        file_name="input_waveform.scs",
        mime="text/plain",
        use_container_width=True,
        disabled=bool(errors),
    )

if errors:
    for error in errors:
        st.error(error)


# ============================================================
# Waveform plot
# ============================================================
if st.session_state.show_wave:
    st.subheader("Waveform Check")
    st.caption(
        "Each card uses the same time axis. Set Viewer Group to overlay related nets in one card."
    )

    prepared = []
    global_max_time = 0.0

    # First pass: build all preview waveforms and determine one common X range.
    for net in st.session_state.nets:
        net_name = net["name"].strip()
        if not net_name:
            continue

        try:
            times, voltages = get_preview_waveform(net)
            wave_type = net["wave_type"]
            delay = 0.0 if wave_type == "DC" else get_delay(net)

            if wave_type == "DC":
                plot_times = times[:]
                plot_voltages = voltages[:]
            else:
                plot_times = [t + delay for t in times]
                plot_voltages = voltages.copy()

                # Before delay Spectre keeps the initial waveform value.
                if delay > 0:
                    plot_times.insert(0, 0.0)
                    plot_voltages.insert(0, voltages[0])

            # PWL holds its last value after the final point; show that explicitly.
            if wave_type == "PWL" and times:
                original_last_time = times[-1]
                extended_time = original_last_time * 1.1 + delay
                if extended_time <= plot_times[-1]:
                    extended_time = plot_times[-1] + max(abs(plot_times[-1]) * 0.1, 1e-12)
                plot_times.append(extended_time)
                plot_voltages.append(voltages[-1])

            # Pulse and finite Bit hold the final value after completion.
            if wave_type == "Pulse" and plot_times:
                extension = max((plot_times[-1] - delay) * 0.1, 1e-12)
                plot_times.append(plot_times[-1] + extension)
                plot_voltages.append(plot_voltages[-1])

            if wave_type == "Bit" and int(net["rpttimes"]) >= 0 and plot_times:
                extension = max(parse_eng(net["bit_period"]), 1e-12)
                plot_times.append(plot_times[-1] + extension)
                plot_voltages.append(plot_voltages[-1])

            if plot_times:
                global_max_time = max(global_max_time, max(plot_times))

            group_name = net.get("group", "").strip()
            # Blank means an individual card. Prefix avoids collisions with user group names.
            group_key = f"group:{group_name}" if group_name else f"net:{net['id']}"
            card_title = group_name if group_name else net_name

            prepared.append({
                "group_key": group_key,
                "card_title": card_title,
                "net_name": net_name,
                "wave_type": wave_type,
                "times": plot_times,
                "voltages": plot_voltages,
                "net": net,
            })

        except Exception as e:
            st.error(f"{net_name}: {e}")

    if prepared:
        # If all sources are DC there is no intrinsic time span. Give the viewer a 1 s axis.
        if global_max_time <= 0:
            global_max_time = 1.0

        # Extend every waveform to the common visible time range.
        # Periodic sources continue generating their real waveform.
        # Finite sources hold their final voltage after completion.
        for item in prepared:
            net = item["net"]
            wave_type = item["wave_type"]
            delay = 0.0 if wave_type == "DC" else get_delay(net)

            if wave_type == "DC":
                dc_value = item["voltages"][0]
                item["times"] = [0.0, global_max_time]
                item["voltages"] = [dc_value, dc_value]

            elif wave_type == "Clock":
                period = parse_eng(net["period"])
                local_end = max(global_max_time - delay, 0.0)
                needed_cycles = max(1, int(math.ceil(local_end / period)))

                preview_net = dict(net)
                preview_net["preview_cycles"] = max(
                    int(net["preview_cycles"]),
                    needed_cycles,
                )
                times, volts = preview_clock(preview_net)
                plot_times = [t + delay for t in times]
                plot_voltages = volts.copy()
                if delay > 0:
                    plot_times.insert(0, 0.0)
                    plot_voltages.insert(0, volts[0])
                item["times"] = plot_times
                item["voltages"] = plot_voltages

            elif wave_type == "Sine":
                freq = parse_eng(net["freq"])
                local_end = max(global_max_time - delay, 0.0)
                needed_cycles = max(1, int(math.ceil(local_end * freq)))

                preview_net = dict(net)
                preview_net["sine_preview_cycles"] = max(
                    int(net["sine_preview_cycles"]),
                    needed_cycles,
                )
                times, volts = preview_sine(preview_net)
                plot_times = [t + delay for t in times]
                plot_voltages = volts.copy()
                if delay > 0:
                    plot_times.insert(0, 0.0)
                    plot_voltages.insert(0, volts[0])
                item["times"] = plot_times
                item["voltages"] = plot_voltages

            elif wave_type == "Bit" and int(net["rpttimes"]) < 0:
                data = normalize_bit_data(net["bit_data"])
                bit_period = parse_eng(net["bit_period"])
                repeat_len = len(data[int(net["rptstart"]) - 1:])
                local_end = max(global_max_time - delay, 0.0)
                needed_bits = max(1, int(math.ceil(local_end / bit_period)))
                extra_bits = max(0, needed_bits - len(data))
                needed_repeats = int(math.ceil(extra_bits / repeat_len)) if repeat_len else 0

                preview_net = dict(net)
                preview_net["bit_preview_repeats"] = max(
                    int(net["bit_preview_repeats"]),
                    needed_repeats,
                )
                times, volts = preview_bit(preview_net)
                plot_times = [t + delay for t in times]
                plot_voltages = volts.copy()
                if delay > 0:
                    plot_times.insert(0, 0.0)
                    plot_voltages.insert(0, volts[0])
                item["times"] = plot_times
                item["voltages"] = plot_voltages

            else:
                # PWL, single Pulse, and finite Bit hold their final state.
                if item["times"] and item["times"][-1] < global_max_time:
                    item["times"].append(global_max_time)
                    item["voltages"].append(item["voltages"][-1])

        groups = {}
        order = []
        for item in prepared:
            key = item["group_key"]
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(item)

        # One Streamlit card + one matplotlib figure per group.
        for key in order:
            items = groups[key]
            title = items[0]["card_title"]

            with st.container(border=True):
                st.markdown(f"#### {title}")

                fig, ax = plt.subplots(figsize=(12, 2.6))
                for item in items:
                    ax.plot(
                        item["times"],
                        item["voltages"],
                        label=item["net_name"],
                    )

                ax.set_xlim(0, global_max_time)
                ax.set_ylabel("Voltage [V]")
                ax.grid(True)

                # Only the bottom card needs the common time-axis label.
                if key == order[-1]:
                    ax.set_xlabel("Time [s]")
                else:
                    ax.set_xlabel("")

                if len(items) > 1:
                    ax.legend()

                fig.tight_layout()
                st.pyplot(fig, use_container_width=True)
                plt.close(fig)
    else:
        st.warning("No valid waveform is available.")


# ============================================================
# Spectre Preview
# ============================================================
st.subheader("Spectre Preview")
st.code(scs_text, language="text")
