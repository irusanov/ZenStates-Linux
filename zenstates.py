#!/usr/bin/env python
import struct
import os
import glob
import argparse
import cpuid
import ctypes
import config as cfg

FID_MAX = 0xFF
FID_MIN = 0x10
DID_MIN = 0x02
DID_MAX = 0x0E
VID_MAX = 0xC8 # 0.300V
VID_MIN = 0x00

PSTATES = range(0xC0010064, 0xC001006C)

MSR_PMGT_MISC =             0xC0010292 # [32] PC6En
MSR_CSTATE_CONFIG =         0xC0010296 # [22] CCR2_CC6EN [14] CCR1_CC6EN [6] CCR0_CC6EN
MSR_HWCR =                  0xC0010015
SMU_CMD_ADDR =              0
SMU_RSP_ADDR =              0
SMU_ARG_ADDR =              0
SMU_CMD_OC_ENABLE =         0
SMU_CMD_OC_DISABLE =        0
SMU_CMD_OC_FREQ_ALL_CORES = 0
SMU_CMD_OC_VID =            0
SMU_CMD_GET_PBO_SCALAR =    0

isOcFreqSupported = False
cpu_sockets = int(os.popen('cat /proc/cpuinfo | grep "physical id" | sort -u | wc -l').read())

def writesmureg(reg, value=0):
    os.popen('setpci -v -s 0:0.0 b8.l={:08X}'.format(reg)).read()
    os.popen('setpci -v -s 0:0.0 bc.l={:08X}'.format(value)).read()

    if cpu_sockets == 2:
        os.popen('setpci -v -s A0:0.0 b8.l={:08X}'.format(reg)).read()
        os.popen('setpci -v -s A0:0.0 bc.l={:08X}'.format(value)).read()


def readsmureg(reg):
    os.popen('setpci -v -s 0:0.0 b8.l={:08X}'.format(reg)).read()
    output = os.popen('setpci -v -s 0:0.0 bc.l').read()

    if cpu_sockets == 2:
        os.popen('setpci -v -s A0:0.0 b8.l={:08X}'.format(reg)).read()
        os.popen('setpci -v -s A0:0.0 bc.l').read()

    return hex(output[-9:][0:8])


def writesmu(cmd, value=0):
    res = False
    # clear the response register
    writesmureg(SMU_RSP_ADDR, 0)
    # write the value
    writesmureg(SMU_ARG_ADDR, value)
    writesmureg(SMU_ARG_ADDR + 4, 0)
    # send the command
    writesmureg(SMU_CMD_ADDR, cmd)
    res = smuwaitdone()
    if res:
        return readsmureg(SMU_RSP_ADDR)
    else:
        return 0


def readsmu(cmd):
    writesmureg(SMU_RSP_ADDR, 0)
    writesmureg(SMU_CMD_ADDR, cmd)
    return readsmureg(SMU_ARG_ADDR)

def smuwaitdone():
    res = False
    timeout = 1000
    data = 0
    while ((not res or data != 1) and timeout > 0):
        timeout-=1
        data = readsmureg(SMU_RSP_ADDR)
        if data == 1:
            res = True
        if (timeout == 0 or data != 1):
            res = False
    return res

def writemsr(msr, val, cpu=-1):
    try:
        if cpu == -1:
            for c in glob.glob('/dev/cpu/[0-9]*/msr'):
                f = os.open(c, os.O_WRONLY)
                os.lseek(f, msr, os.SEEK_SET)
                os.write(f, struct.pack('Q', val))
                os.close(f)
        else:
            f = os.open('/dev/cpu/%d/msr' % (cpu), os.O_WRONLY)
            os.lseek(f, msr, os.SEEK_SET)
            os.write(f, struct.pack('Q', val))
            os.close(f)
    except:
        raise OSError("msr module not loaded (run modprobe msr)")


def readmsr(msr, cpu=0):
    try:
        f = os.open('/dev/cpu/%d/msr' % cpu, os.O_RDONLY)
        os.lseek(f, msr, os.SEEK_SET)
        val = struct.unpack('Q', os.read(f, 8))[0]
        os.close(f)
        return val
    except:
        raise OSError("msr module not loaded (run modprobe msr)")


def pstate2str(val):
    if val & (1 << 63):
        fid = val & 0xff
        did = val >> 8 & 0x3f
        vid = val >> 14 & 0xff
        ratio = 25*fid/(12.5 * did)
        vcore = vidToVolts(vid)
        return "Enabled - FID = %X - DID = %X - VID = %X - Ratio = %.2f - vCore = %.5f" % (fid, did, vid, ratio, vcore)
    else:
        return "Disabled"


def pstateToGuiString(fid, did, vid):
    ratio = 25 * int(fid)/(12.5 * int(did))
    vcore = vidToVolts(vid)
    return "Ratio = %.2f - vCore = %.5f" % (ratio, vcore)


def getPstateFid(index):
    return readmsr(PSTATES[index]) & 0xff


def getPstateDid(index):
    return readmsr(PSTATES[index]) >> 8 & 0x3f


def getPstateVid(index):
    return readmsr(PSTATES[index]) >> 14 & 0xff


def getCurrentVid():
    return readmsr(0xC0010293) >> 14 & 0xff


def getPstateDetails(val):
    fid = val & 0xff
    did = val >> 8 & 0x3f
    vid = val >> 14 & 0xff
    return [fid, did, vid]


def getRatio(msr):
    val = readmsr(msr)
    fid = val & 0xff
    did = val >> 8 & 0x3f
    return 25*fid/(12.5 * did)


def calculateFrequencyFromFid(msr, fid):
    did = readmsr(msr) >> 8 & 0x3f
    if fid not in range(FID_MIN, FID_MAX):
        fid = 0x88 # 1.00V
    return int(25*fid/(12.5 * did) * 100)


def vidToVolts(vid):
    return 1.55 - vid * 0.00625


def voltsToVid(volts):
    return (1.55 - volts) / 0.00625


def getCpuidRegs(fn):
    if args.libcpuid:
        regs = (ctypes.c_uint32 * 4)(fn, 0, 0, 0)
        cpuid(regs)
    else:
        regs = cpuid.CPUID()(fn)
    return regs

def getCpuid():
    eax, ebx, ecx, edx = getCpuidRegs(0x00000001)
    print("CPUID: %08X" % eax)
    return eax


def getPkgType():
    eax, ebx, ecx, edx = getCpuidRegs(0x80000001)
    type = ebx >> 28
    print("Package Type: %01d" % type)
    return type


def getOcMode():
    return readsmu(SMU_CMD_GET_PBO_SCALAR) == 0


def getC6core():
    return readmsr(MSR_CSTATE_CONFIG) & ((1 << 22) | (1 << 14) | (1 << 6)) == ((1 << 22) | (1 << 14) | (1 << 6))


def getC6package():
    return readmsr(MSR_PMGT_MISC) & (1 << 32) != 0


def setC6Core(enable):
    if not getC6core() and enable:
        writemsr(MSR_CSTATE_CONFIG, readmsr(MSR_CSTATE_CONFIG) | ((1 << 22) | (1 << 14) | (1 << 6)))
        print('GUI: Set C6-Core: %s' % str(enable))
    elif getC6core() and not enable:
        writemsr(MSR_CSTATE_CONFIG, readmsr(MSR_CSTATE_CONFIG) & ~ ((1 << 22) | (1 << 14) | (1 << 6)))
        print('GUI: Set C6-Core: %s' % str(enable))


def setC6Package(enable):
    if not getC6package() and enable:
        writemsr(MSR_PMGT_MISC, readmsr(MSR_PMGT_MISC) | (1 << 32))
        print('GUI: Set C6-Package: %s' % str(enable))
    elif getC6package() and  not enable:
        writemsr(MSR_PMGT_MISC, readmsr(MSR_PMGT_MISC) & ~(1 << 32))
        print('GUI: Set C6-Package: %s' % str(enable))


def setPPT(val):
    if int(val) > -1: writesmu(0x53, int(val) * 1000)


def setTDC(val):
    if int(val) > -1: writesmu(0x54, int(val) * 1000)


def setEDC(val):
    if int(val) > -1: writesmu(0x55, int(val) * 1000)


# Not supported yet
def setScalar(val):
    if int(val) > 0 and int(val) <= 10: print('PBO Scalar')


def setPboLimits(ppt, tdc, edc, scalar):
    setPPT(ppt)
    setTDC(tdc)
    setEDC(edc)
    setScalar(scalar)


def setbits(val, base, length, new):
    return (val ^ (val & ((2 ** length - 1) << base))) + (new << base)


def setfid(val, new):
    return setbits(val, 0, 8, new)


def setdid(val, new):
    return setbits(val, 8, 6, new)


def setvid(val, new):
    return setbits(val, 14, 8, new)


def hex(x):
    return int(x, 16)


def setPstateGui(index, fid, did, vid):
    new = old = readmsr(PSTATES[index])
    if fid in range(FID_MIN, FID_MAX):
        new = setfid(new, fid)
    if did in range(DID_MIN, DID_MAX):
        new = setdid(new, did)
    if vid in range(VID_MIN, VID_MAX):
        new = setvid(new, vid)
    if new != old:
        if not (readmsr(MSR_HWCR) & (1 << 21)):
            print('GUI: Locking TSC frequency')
            for c in range(len(glob.glob('/dev/cpu/[0-9]*/msr'))):
                writemsr(MSR_HWCR, readmsr(MSR_HWCR, c) | (1 << 21), c)
        print('GUI: Set Pstate%s: %s' % (index, getPstateDetails(new)))
        writemsr(PSTATES[index], new)

parser = argparse.ArgumentParser(description='Dynamically edit AMD Ryzen processor parameters')
parser.add_argument('-l', '--list', action='store_true', help='List all P-States')
parser.add_argument('--no-gui', action='store_true', help='Run in CLI without GUI')
parser.add_argument('--libcpuid', action='store_true', help='Use libcpuid instead of cpuid.py')
parser.add_argument('-p', '--pstate', default=-1, type=int, choices=range(8), help='P-State to set')
parser.add_argument('--enable', action='store_true', help='Enable P-State')
parser.add_argument('--disable', action='store_true', help='Disable P-State')
parser.add_argument('-f', '--fid', default=-1, type=hex, help='FID to set (in hex)')
parser.add_argument('-d', '--did', default=-1, type=hex, help='DID to set (in hex)')
parser.add_argument('-v', '--vid', default=-1, type=hex, help='VID to set (in hex)')
parser.add_argument('--c6-enable', action='store_true', help='Enable C-State C6')
parser.add_argument('--c6-disable', action='store_true', help='Disable C-State C6')
parser.add_argument('--smu-test-message', action='store_true', help='Send test message to the SMU (response 1 means "success")')
parser.add_argument('--oc-enable', action='store_true', help='Enable OC')
parser.add_argument('--oc-disable', action='store_true', help='Disable OC')
parser.add_argument('--oc-frequency', default=550, type=int, help='Set overclock frequency (in MHz)')
parser.add_argument('--oc-vid', default=-1, type=hex, help='Set overclock VID')
parser.add_argument('--ppt', default=-1, type=int, help='Set PPT limit (in W)')
parser.add_argument('--tdc', default=-1, type=int, help='Set TDC limit (in A)')
parser.add_argument('--edc', default=-1, type=int, help='Set EDC limit (in A)')

args = parser.parse_args()

if (not args.list
    and args.pstate == -1
    and not args.c6_enable
    and not args.c6_disable
    and not args.smu_test_message
    and not args.oc_disable
    and not args.oc_enable
    and args.no_gui
    and args.edc == -1
    and args.ppt == -1
    and args.tdc == -1):
        parser.print_help()
        exit()

if args.libcpuid:
    cpuid = ctypes.CDLL("libcpuid.so").cpu_exec_cpuid_ext
    cpuid.restype = None
    cpuid.argtypes = [ctypes.POINTER(ctypes.c_uint32)]

print('CPUs: %d' % cpu_sockets)

_cpuid = getCpuid()
_pkgtype = getPkgType()

# Zen | Summit Ridge, Threadripper
if _cpuid in [0x00800F11, 0x00800F00]:
    SMU_CMD_ADDR = 0x03B10528
    SMU_RSP_ADDR = 0x03B10564
    SMU_ARG_ADDR = 0x03B10598
    SMU_CMD_OC_ENABLE = 0x23
    SMU_CMD_OC_DISABLE = 0x24
    SMU_CMD_OC_FREQ_ALL_CORES = 0x26
    SMU_CMD_OC_VID = 0x28
    # depends on SMU version. Need to find which version disables the manual OC
    # turn it off for now
    isOcFreqSupported = False

# Zen | Naples - P-States only
elif _cpuid == 0x00800F12:
    SMU_CMD_ADDR = 0x03B10528
    SMU_RSP_ADDR = 0x03B10564
    SMU_ARG_ADDR = 0x03B10598
    isOcFreqSupported = False

# Zen+ | Pinnacle Ridge, Colfax
elif _cpuid == 0x00800F82:
    SMU_CMD_ADDR = 0x03B1051C
    SMU_RSP_ADDR = 0x03B10568
    SMU_ARG_ADDR = 0x03B10590
    # SMU_CMD_OC_ENABLE = 0x63
    # SMU_CMD_OC_DISABLE = 0x64
    isOcFreqSupported = True

    if _pkgtype == 7: # Colfax
        SMU_CMD_OC_ENABLE = 0x67 # based on assumption
        SMU_CMD_OC_FREQ_ALL_CORES = 0x68
        SMU_CMD_OC_VID = 0x6A
        SMU_CMD_GET_PBO_SCALAR = 0x70
    else:
        SMU_CMD_OC_ENABLE = 0x6B
        SMU_CMD_OC_FREQ_ALL_CORES = 0x6C
        SMU_CMD_OC_VID = 0x6E
        SMU_CMD_GET_PBO_SCALAR = 0x6F

# Zen 2 | Matisse, Rome, Castle Peak
# Zen 3 | Vermeer
elif _cpuid in [0x00870F10, 0x00870F00, 0x00830F00, 0x00830F10, 0x00A20F00, 0x00A20F10]:
    SMU_CMD_ADDR = 0x03B10524
    SMU_RSP_ADDR = 0x03B10570
    SMU_ARG_ADDR = 0x03B10A40
    isOcFreqSupported = True

    if _pkgtype == 7: # Rome ES
        SMU_CMD_OC_FREQ_ALL_CORES = 0x18
        SMU_CMD_OC_VID = 0x12
    else:
        SMU_CMD_OC_ENABLE = 0x5A
        SMU_CMD_OC_DISABLE = 0x5B
        SMU_CMD_OC_FREQ_ALL_CORES = 0x5C
        SMU_CMD_OC_VID = 0x61
        SMU_CMD_GET_PBO_SCALAR = 0x6C

# RavenRidge, RavenRidge2
elif _cpuid in [0x00810F00, 0x00810F10, 0x00820F00]:
    SMU_CMD_ADDR = 0x03B10528
    SMU_RSP_ADDR = 0x03B10564
    SMU_ARG_ADDR = 0x03B10998
    isOcFreqSupported = False

# Picasso, Fenghuang
elif _cpuid in [0x00810F81, 0x00850F00]:
    SMU_CMD_ADDR = 0x03B10A20
    SMU_RSP_ADDR = 0x03B10A80
    SMU_ARG_ADDR = 0x03B10A88
    SMU_CMD_OC_ENABLE = 0x69
    SMU_CMD_OC_DISABLE = 0x6A
    SMU_CMD_OC_FREQ_ALL_CORES = 0x7D
    SMU_CMD_OC_VID = 0x7F
    SMU_CMD_GET_PBO_SCALAR = 0x62
    isOcFreqSupported = True

# Renoir
elif _cpuid in [0x00860F01]:
    SMU_CMD_ADDR = 0x03B10A20
    SMU_RSP_ADDR = 0x03B10A80
    SMU_ARG_ADDR = 0x03B10A88
    SMU_CMD_GET_PBO_SCALAR = 0xF
    isOcFreqSupported = False

else:
    exit('CPU not supported!')

if args.list:
    for p in range(len(PSTATES)):
        print('P' + str(p) + " - " + pstate2str(readmsr(PSTATES[p])))
    print('C6 State - Package - ' +
          ('Enabled' if getC6package() else 'Disabled'))
    print('C6 State - Core - ' + ('Enabled' if getC6core() else 'Disabled'))

if args.pstate >= 0:
    new = old = readmsr(PSTATES[args.pstate])
    print('Current P' + str(args.pstate) + ': ' + pstate2str(old))
    if args.enable:
        new = setbits(new, 63, 1, 1)
        print('Enabling state')
    if args.disable:
        new = setbits(new, 63, 1, 0)
        print('Disabling state')
    if args.fid in range(FID_MIN, FID_MAX):
        new = setfid(new, args.fid)
        print('Setting FID to %X' % args.fid)
    if args.did >= 0:
        new = setdid(new, args.did)
        print('Setting DID to %X' % args.did)
    if args.vid in range(VID_MIN, VID_MAX):
        new = setvid(new, args.vid)
        print('Setting VID to %X' % args.vid)
    if new != old:
        if not (readmsr(MSR_HWCR) & (1 << 21)):
            print('Locking TSC frequency')
            for c in range(len(glob.glob('/dev/cpu/[0-9]*/msr'))):
                writemsr(MSR_HWCR, readmsr(MSR_HWCR, c) | (1 << 21), c)
        print('New P' + str(args.pstate) + ': ' + pstate2str(new))
        writemsr(PSTATES[args.pstate], new)

if args.c6_enable:
    setC6Package(True)
    setC6Core(True)
    print('Enabling C6 state')

if args.c6_disable:
    setC6Package(False)
    setC6Core(False)
    print('Disabling C6 state')

if args.smu_test_message:
    print('Sending test SMU message')
    print('SMU response: %X' % writesmu(0x1))

if args.oc_enable:
    if isOcFreqSupported:
        writesmu(SMU_CMD_OC_ENABLE)
        print('Enable OC Mode')
    else:
        print('OC Mode not supported')

if args.oc_disable:
    if isOcFreqSupported:
        writesmu(SMU_CMD_OC_DISABLE)
        print('Disabling OC Mode')
    else:
        print('OC Mode not supported')

if args.oc_vid >= 0:
    writesmu(SMU_CMD_OC_VID, args.oc_vid)
    print('Set OC VID to %X' % args.oc_vid)

if args.oc_frequency > 550:
    writesmu(SMU_CMD_OC_FREQ_ALL_CORES, args.oc_frequency)
    print('Set OC frequency to %sMHz' % args.oc_frequency)

if args.ppt > -1:
    setPPT(args.ppt)
    print('Set PPT to %sW' % args.ppt)

if args.tdc > -1:
    setTDC(args.tdc)
    print('Set TDC to %sA' % args.tdc)

if args.edc > -1:
    setEDC(args.edc)
    print('Set EDC to %sA' % args.edc)


###############################
# GUI
if not args.no_gui:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    builder = Gtk.Builder()
    builder.add_from_file("gtk.glade")

    oc_mode_checkbox = builder.get_object("ocModeCheckbox")
    frequency_input = builder.get_object("frequencyInput")
    voltage_input = builder.get_object("voltageInput")
    tabs = builder.get_object("tabs")


    class Handler:
        def onDestroy(self, *args):
            Gtk.main_quit()

        def onRefreshButtonClicked(self):
            App.init_values()

        def on_ocModeCheckbox_toggled(self):
            active = oc_mode_checkbox.get_active()
            frequency_input.set_sensitive(active)
            voltage_input.set_sensitive(active)

        def on_applyButton_clicked(self):
            if (tabs.get_current_page() == 0):
                apply_cpu_tab_settings()


    class App:
        def init_values():
            _oc_mode = getOcMode()
            if _oc_mode:
                _default_vid = getCurrentVid()
                _ratio = getRatio(0xC0010293)
            else:
                _default_vid = getPstateVid(0)
                _ratio = getRatio(PSTATES[0])

            _current_freq = int(_ratio * 100)
            _current_voltage = vidToVolts(_default_vid)

            oc_mode_checkbox.set_active(_oc_mode)
            frequency_input.set_value(_current_freq)
            voltage_input.set_value(_current_voltage)

            Handler.on_ocModeCheckbox_toggled(Handler)

    def apply_cpu_tab_settings():
        if oc_mode_checkbox.get_active():
            freq = int(frequency_input.get_value())
            vid = int(voltsToVid(voltage_input.get_value()))
            writesmu(SMU_CMD_OC_ENABLE)
            writesmu(SMU_CMD_OC_FREQ_ALL_CORES, freq)
            writesmu(SMU_CMD_OC_VID, vid)
        else:
            writesmu(SMU_CMD_OC_DISABLE)


    builder.connect_signals(Handler)

    App.init_values()

    window = builder.get_object("appWindow")
    window.set_title(cfg.APP_NAME + " v" + cfg.APP_VERSION);
    window.show_all()

    Gtk.main()
