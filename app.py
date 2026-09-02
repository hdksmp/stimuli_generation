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
    unsafe_allow_html=True
)

st.title("Spectre Input Waveform Generator")
st.caption("Simulator input waveform checker / Spectre PWL source generator")


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
    """
    Engineering notation -> float

    Examples:
        10u   -> 10e-6
        100n  -> 100e-9
        3.3   -> 3.3
    """

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
    """
    Float -> compact Spectre-friendly string
    """

    if abs(value) < 1e-30:
        return "0"

    return f"{value:.12g}"


# ============================================================
# PWL parser
# ============================================================
def parse_waveform(text):

    tokens = text.split()

    if len(tokens) == 0:
        raise ValueError("Waveform is empty.")

    if len(tokens) % 2 != 0:
        raise ValueError(
            "Waveform must be: "
            "'time1 voltage1 time2 voltage2 ...'"
        )

    times = []
    voltages = []

    for i in range(0, len(tokens), 2):

        t = parse_eng(tokens[i])
        v = parse_eng(tokens[i + 1])

        times.append(t)
        voltages.append(v)

    for i in range(1, len(times)):

        if times[i] < times[i - 1]:
            raise ValueError(
                "Time must be monotonically increasing."
            )

    return times, voltages


# ============================================================
# Convert points -> Spectre PWL text
# ============================================================
def points_to_pwl(times, voltages):

    result = []

    for t, v in zip(times, voltages):
        result.append(format_value(t))
        result.append(format_value(v))

    return " ".join(result)


# ============================================================
# Pulse generator
#
#          ┌────────────┐
#          │            │
#          │            │
#   _______│            │_______
#
#          <- width ->
#
# rise/fall are explicitly represented.
# Global Delay is handled separately by Spectre delay=
# ============================================================
def generate_pulse(net):

    vlow = parse_eng(net["vlow"])
    vhigh = parse_eng(net["vhigh"])

    rise = parse_eng(net["rise"])
    width = parse_eng(net["width"])
    fall = parse_eng(net["fall"])

    if rise < 0:
        raise ValueError("Rise time must be >= 0.")

    if width < 0:
        raise ValueError("Pulse width must be >= 0.")

    if fall < 0:
        raise ValueError("Fall time must be >= 0.")

    times = [
        0,
        rise,
        rise + width,
        rise + width + fall,
    ]

    voltages = [
        vlow,
        vhigh,
        vhigh,
        vlow,
    ]

    return times, voltages


# ============================================================
# Clock generator
#
# Period:
#
#     ┌───────┐        ┌───────┐
#     │       │        │       │
# ____│       │________│       │____
#
# Duty controls High duration.
# Global Delay is handled separately.
# ============================================================
def generate_clock(net):

    vlow = parse_eng(net["vlow"])
    vhigh = parse_eng(net["vhigh"])

    period = parse_eng(net["period"])
    rise = parse_eng(net["rise"])
    fall = parse_eng(net["fall"])

    duty = float(net["duty"])
    cycles = int(net["cycles"])

    if period <= 0:
        raise ValueError("Period must be > 0.")

    if rise < 0:
        raise ValueError("Rise time must be >= 0.")

    if fall < 0:
        raise ValueError("Fall time must be >= 0.")

    if duty <= 0 or duty >= 100:
        raise ValueError(
            "Duty must be between 0 and 100."
        )

    if cycles < 1:
        raise ValueError(
            "Cycles must be >= 1."
        )

    high_time = period * duty / 100.0

    # rise and fall must fit inside one clock period
    if rise + fall >= period:
        raise ValueError(
            "Rise + Fall must be smaller than Period."
        )

    # high plateau end
    fall_start = high_time

    if fall_start < rise:
        raise ValueError(
            "Duty is too small for the specified Rise time."
        )

    times = []
    voltages = []

    for cycle in range(cycles):

        t0 = cycle * period

        # Low
        times.append(t0)
        voltages.append(vlow)

        # Rising edge end
        times.append(t0 + rise)
        voltages.append(vhigh)

        # Falling edge start
        times.append(t0 + fall_start)
        voltages.append(vhigh)

        # Falling edge end
        times.append(t0 + fall_start + fall)
        voltages.append(vlow)

        # End of period
        times.append(t0 + period)
        voltages.append(vlow)

    return times, voltages


# ============================================================
# Get waveform for selected type
# ============================================================
def get_waveform(net):

    wave_type = net["wave_type"]

    if wave_type == "PWL":

        return parse_waveform(
            net["waveform"]
        )

    elif wave_type == "Pulse":

        return generate_pulse(net)

    elif wave_type == "Clock":

        return generate_clock(net)

    else:

        raise ValueError(
            f"Unknown waveform type: {wave_type}"
        )


# ============================================================
# Spectre source instance name
# ============================================================
def source_name(net_name):

    safe_name = re.sub(
        r"[^a-zA-Z0-9_]",
        "_",
        net_name,
    )

    if not safe_name:
        safe_name = "net"

    return "_v_" + safe_name


# ============================================================
# Generate Spectre .scs
# ============================================================
def generate_scs(cell_name, nets):

    lines = []

    lines.append(
        "// ==============================================="
    )
    lines.append(
        "// Generated by Spectre Input Waveform Generator"
    )
    lines.append(
        "// ==============================================="
    )
    lines.append("")

    for net in nets:

        net_name = net["name"].strip()

        if not net_name:
            continue

        try:

            times, voltages = get_waveform(net)

            waveform = points_to_pwl(
                times,
                voltages,
            )

        except Exception:
            continue

        delay = net["delay"].strip()

        if not delay:
            delay = "0"

        src_name = source_name(net_name)

        # AMS mode
        if cell_name.strip():

            target_net = (
                f"{cell_name.strip()}.{net_name}"
            )

        # Spectre mode
        else:

            target_net = net_name

        line = (
            f"{src_name} "
            f"( {target_net} 0 ) "
            f"vsource "
            f"wave = [ {waveform} ] "
            f'delay={delay} '
            f"type = pwl"
        )

        lines.append(line)

    lines.append("")

    return "\n".join(lines)


# ============================================================
# Default Net settings
# ============================================================
def create_default_net(net_id):

    return {

        "id": net_id,

        "name": "",

        "wave_type": "PWL",

        # PWL
        "waveform":
            "0 0 10u 0 10.1u 3.3",

        # common
        "delay": "0",

        # Pulse / Clock
        "vlow": "0",
        "vhigh": "3.3",

        "rise": "100n",
        "fall": "100n",

        # Pulse
        "width": "10u",

        # Clock
        "period": "20u",
        "duty": 50.0,
        "cycles": 5,
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
    help=(
        "AMS simulation only. "
        "Leave blank for normal Spectre simulation."
    ),
)

if cell_name:

    st.info(
        f"AMS mode : target net = "
        f"`{cell_name}.net_name`"
    )

else:

    st.info(
        "Spectre mode : target net = `net_name`"
    )


st.divider()


# ============================================================
# Add Net
# ============================================================
col_title, col_add = st.columns([6, 2])

with col_title:
    st.subheader("Input Nets")

with col_add:

    if st.button(
        "➕ Add Net",
        use_container_width=True,
    ):

        net_id = st.session_state.next_net_id

        st.session_state.nets.append(
            create_default_net(net_id)
        )

        st.session_state.next_net_id += 1

        st.rerun()


# ============================================================
# Net forms
# ============================================================
delete_id = None


for index, net in enumerate(
    st.session_state.nets
):

    net_id = net["id"]

    with st.container(border=True):

        title_col, delete_col = st.columns(
            [6, 2]
        )

        with title_col:

            st.markdown(
                f"### Net {index + 1}"
            )

        with delete_col:

            if st.button(
                "🗑 Delete",
                key=f"delete_{net_id}",
                use_container_width=True,
            ):

                delete_id = net_id

        # ----------------------------------------
        # Net name + waveform type
        # ----------------------------------------
        col1, col2 = st.columns([2, 1])

        with col1:

            net["name"] = st.text_input(
                "Net name",
                value=net["name"],
                key=f"net_name_{net_id}",
                placeholder="Example: vin",
            )

        with col2:

            net["wave_type"] = st.selectbox(
                "Waveform Type",
                [
                    "PWL",
                    "Pulse",
                    "Clock",
                ],
                index=[
                    "PWL",
                    "Pulse",
                    "Clock",
                ].index(
                    net["wave_type"]
                ),
                key=f"wave_type_{net_id}",
            )

        # ========================================
        # PWL
        # ========================================
        if net["wave_type"] == "PWL":

            net["waveform"] = st.text_input(
                "PWL waveform",
                value=net["waveform"],
                key=f"waveform_{net_id}",
                placeholder=(
                    "0 1 10u 2.5 30u 1"
                ),
                help=(
                    "time1 voltage1 "
                    "time2 voltage2 ..."
                ),
            )

        # ========================================
        # Pulse
        # ========================================
        elif net["wave_type"] == "Pulse":

            st.caption(
                "Single pulse waveform"
            )

            c1, c2 = st.columns(2)

            with c1:

                net["vlow"] = st.text_input(
                    "Initial / Low Voltage",
                    value=net["vlow"],
                    key=f"pulse_low_{net_id}",
                )

            with c2:

                net["vhigh"] = st.text_input(
                    "High Voltage",
                    value=net["vhigh"],
                    key=f"pulse_high_{net_id}",
                )

            c1, c2, c3 = st.columns(3)

            with c1:

                net["rise"] = st.text_input(
                    "Rise Time",
                    value=net["rise"],
                    key=f"pulse_rise_{net_id}",
                )

            with c2:

                net["width"] = st.text_input(
                    "Pulse Width",
                    value=net["width"],
                    key=f"pulse_width_{net_id}",
                )

            with c3:

                net["fall"] = st.text_input(
                    "Fall Time",
                    value=net["fall"],
                    key=f"pulse_fall_{net_id}",
                )

        # ========================================
        # Clock
        # ========================================
        elif net["wave_type"] == "Clock":

            st.caption(
                "Periodic clock waveform"
            )

            c1, c2 = st.columns(2)

            with c1:

                net["vlow"] = st.text_input(
                    "Initial / Low Voltage",
                    value=net["vlow"],
                    key=f"clock_low_{net_id}",
                )

            with c2:

                net["vhigh"] = st.text_input(
                    "High Voltage",
                    value=net["vhigh"],
                    key=f"clock_high_{net_id}",
                )

            c1, c2, c3 = st.columns(3)

            with c1:

                net["period"] = st.text_input(
                    "Period",
                    value=net["period"],
                    key=f"clock_period_{net_id}",
                )

            with c2:

                net["rise"] = st.text_input(
                    "Rise Time",
                    value=net["rise"],
                    key=f"clock_rise_{net_id}",
                )

            with c3:

                net["fall"] = st.text_input(
                    "Fall Time",
                    value=net["fall"],
                    key=f"clock_fall_{net_id}",
                )

            c1, c2 = st.columns(2)

            with c1:

                net["duty"] = st.number_input(
                    "Duty [%]",
                    min_value=0.1,
                    max_value=99.9,
                    value=float(net["duty"]),
                    step=1.0,
                    key=f"clock_duty_{net_id}",
                )

            with c2:

                net["cycles"] = st.number_input(
                    "Number of Cycles",
                    min_value=1,
                    value=int(net["cycles"]),
                    step=1,
                    key=f"clock_cycles_{net_id}",
                )

        # ========================================
        # Common delay
        # ========================================
        net["delay"] = st.text_input(
            "Delay",
            value=net["delay"],
            key=f"delay_{net_id}",
            placeholder="0",
            help=(
                "Spectre vsource delay parameter. "
                "Example: 10u"
            ),
        )


# ============================================================
# Delete
# ============================================================
if delete_id is not None:

    st.session_state.nets = [
        net
        for net in st.session_state.nets
        if net["id"] != delete_id
    ]

    st.rerun()


st.divider()


# ============================================================
# Validate all Net waveforms
# ============================================================
errors = []

for net in st.session_state.nets:

    if not net["name"].strip():
        continue

    try:

        get_waveform(net)

        parse_eng(
            net["delay"]
            if net["delay"].strip()
            else "0"
        )

    except Exception as e:

        errors.append(
            f'{net["name"]}: {e}'
        )


# ============================================================
# Wave Check / Dump
# ============================================================
button_col1, button_col2 = st.columns(2)


with button_col1:

    if st.button(
        "📈 Wave Check",
        type="primary",
        use_container_width=True,
    ):

        st.session_state.show_wave = True


scs_text = generate_scs(
    cell_name,
    st.session_state.nets,
)


with button_col2:

    st.download_button(
        "💾 .scs Dump",
        data=scs_text,
        file_name="input_waveform.scs",
        mime="text/plain",
        use_container_width=True,
        disabled=bool(errors),
    )


# ============================================================
# Error display
# ============================================================
if errors:

    for error in errors:

        st.error(error)


# ============================================================
# Waveform plot
# ============================================================
if st.session_state.show_wave:

    st.subheader("Waveform Check")

    fig, ax = plt.subplots(
        figsize=(12, 5)
    )

    valid_count = 0

    for net in st.session_state.nets:

        net_name = net["name"].strip()

        if not net_name:
            continue

        try:

            times, voltages = get_waveform(net)

            delay = parse_eng(
                net["delay"]
                if net["delay"].strip()
                else "0"
            )

            # ----------------------------------------
            # Delay applied waveform
            # ----------------------------------------
            plot_times = [
                t + delay
                for t in times
            ]

            plot_voltages = voltages.copy()


            # ----------------------------------------
            # Before delay:
            # keep the first voltage
            # ----------------------------------------
            if delay > 0:

                first_voltage = voltages[0]

                plot_times.insert(
                    0,
                    0.0,
                )

                plot_voltages.insert(
                    0,
                    first_voltage,
                )


            # ----------------------------------------
            # PWL:
            # extend the final value to
            # 1.1 x final original time
            # ----------------------------------------
            if (
                net["wave_type"] == "PWL"
                and len(times) > 0
            ):

                original_last_time = times[-1]

                extended_time = (
                    original_last_time * 1.1
                    + delay
                )

                if extended_time <= plot_times[-1]:
                    extended_time = (
                        plot_times[-1] + 1e-9
                    )

                plot_times.append(
                    extended_time
                )

                plot_voltages.append(
                    voltages[-1]
                )


            ax.plot(
                plot_times,
                plot_voltages,
                marker="o",
                label=net_name,
            )

            valid_count += 1

        except Exception as e:

            st.error(
                f"{net_name}: {e}"
            )


    if valid_count:

        ax.set_xlabel("Time [s]")
        ax.set_ylabel("Voltage [V]")

        ax.grid(True)
        ax.legend()

        st.pyplot(fig)

    else:

        st.warning(
            "No valid waveform is available."
        )

    plt.close(fig)


# ============================================================
# Spectre Preview
# ============================================================
st.subheader("Spectre Preview")

st.code(
    scs_text,
    language="text",
)