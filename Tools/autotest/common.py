from __future__ import print_function

import abc
import math
import os
import shutil
import sys
import time
import pexpect

from pymavlink import mavwp, mavutil
from pysim import util, vehicleinfo

MAVLINK_SET_POS_TYPE_MASK_POS_IGNORE = ((1 << 0) | (1 << 1) | (1 << 2))
MAVLINK_SET_POS_TYPE_MASK_VEL_IGNORE = ((1 << 3) | (1 << 4) | (1 << 5))
MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE = ((1 << 6) | (1 << 7) | (1 << 8))
MAVLINK_SET_POS_TYPE_MASK_FORCE = (1 << 9)
MAVLINK_SET_POS_TYPE_MASK_YAW_IGNORE = (1 << 10)
MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE = (1 << 11)

MAV_FRAMES = {"MAV_FRAME_GLOBAL": mavutil.mavlink.MAV_FRAME_GLOBAL,
              "MAV_FRAME_GLOBAL_INT": mavutil.mavlink.MAV_FRAME_GLOBAL_INT,
              "MAV_FRAME_GLOBAL_RELATIVE_ALT": mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
              "MAV_FRAME_GLOBAL_RELATIVE_ALT_INT": mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
              "MAV_FRAME_GLOBAL_TERRAIN_ALT": mavutil.mavlink.MAV_FRAME_GLOBAL_TERRAIN_ALT,
              "MAV_FRAME_GLOBAL_TERRAIN_ALT_INT": mavutil.mavlink.MAV_FRAME_GLOBAL_TERRAIN_ALT_INT}

# a list of pexpect objects to read while waiting for
# messages. This keeps the output to stdout flowing
expect_list = []

# get location of scripts
testdir = os.path.dirname(os.path.realpath(__file__))

# Check python version for abstract base class
if sys.version_info[0] >= 3 and sys.version_info[1] >= 4:
        ABC = abc.ABC
else:
    ABC = abc.ABCMeta('ABC', (), {})


class ErrorException(Exception):
    """Base class for other exceptions"""
    pass


class AutoTestTimeoutException(ErrorException):
    pass


class WaitModeTimeout(AutoTestTimeoutException):
    """Thrown when fails to achieve given mode change."""
    pass


class WaitAltitudeTimout(AutoTestTimeoutException):
    """Thrown when fails to achieve given altitude range."""
    pass


class WaitGroundSpeedTimeout(AutoTestTimeoutException):
    """Thrown when fails to achieve given ground speed range."""
    pass


class WaitRollTimeout(AutoTestTimeoutException):
    """Thrown when fails to achieve given roll in degrees."""
    pass


class WaitPitchTimeout(AutoTestTimeoutException):
    """Thrown when fails to achieve given pitch in degrees."""
    pass


class WaitHeadingTimeout(AutoTestTimeoutException):
    """Thrown when fails to achieve given heading."""
    pass


class WaitDistanceTimeout(AutoTestTimeoutException):
    """Thrown when fails to attain distance"""
    pass


class WaitLocationTimeout(AutoTestTimeoutException):
    """Thrown when fails to attain location"""
    pass


class WaitWaypointTimeout(AutoTestTimeoutException):
    """Thrown when fails to attain waypoint ranges"""
    pass


class SetRCTimeout(AutoTestTimeoutException):
    """Thrown when fails to send RC commands"""
    pass


class MsgRcvTimeoutException(AutoTestTimeoutException):
    """Thrown when fails to receive an expected message"""
    pass


class NotAchievedException(ErrorException):
    """Thrown when fails to achieve a goal"""
    pass


class YawSpeedNotAchievedException(NotAchievedException):
    """Thrown when fails to achieve given yaw speed."""
    pass


class SpeedVectorNotAchievedException(NotAchievedException):
    """Thrown when fails to achieve given speed vector."""
    pass


class PreconditionFailedException(ErrorException):
    """Thrown when a precondition for a test is not met"""
    pass


class Context(object):
    def __init__(self):
        self.parameters = []

class AutoTest(ABC):
    """Base abstract class.
    It implements the common function for all vehicle types.
    """
    def __init__(self,
                 viewerip=None,
                 use_map=False):
        self.mavproxy = None
        self.mav = None
        self.viewerip = viewerip
        self.use_map = use_map
        self.contexts = []
        self.context_push()
        self.buildlog = None
        self.copy_tlog = False
        self.logfile = None

    @staticmethod
    def progress(text):
        """Display autotest progress text."""
        print("AUTOTEST: " + text)

    # following two functions swiped from autotest.py:
    @staticmethod
    def buildlogs_dirpath():
        return os.getenv("BUILDLOGS", util.reltopdir("../buildlogs"))

    def buildlogs_path(self, path):
        '''return a string representing path in the buildlogs directory'''
        bits = [self.buildlogs_dirpath()]
        if isinstance(path, list):
            bits.extend(path)
        else:
            bits.append(path)
        return os.path.join(*bits)

    def sitl_streamrate(self):
        '''allow subclasses to override SITL streamrate'''
        return 10

    def autotest_connection_hostport(self):
        '''returns host and port of connection between MAVProxy and autotest,
        colon-separated'''
        return "127.0.0.1:19550"

    def autotest_connection_string_from_mavproxy(self):
        return "tcpin:" + self.autotest_connection_hostport()

    def autotest_connection_string_to_mavproxy(self):
        return "tcp:" + self.autotest_connection_hostport()

    def mavproxy_options(self):
        '''returns options to be passed to MAVProxy'''
        ret = ['--sitl=127.0.0.1:5501',
               '--out=' + self.autotest_connection_string_from_mavproxy(),
               '--streamrate=%u' % self.sitl_streamrate()]
        if self.viewerip:
            ret.append("--out=%s:14550" % self.viewerip)
        if self.use_map:
            ret.append('--map')

        return ret

    def vehicleinfo_key(self):
        return self.log_name

    def apply_defaultfile_parameters(self):
        '''apply parameter file'''

        # setup test parameters
        vinfo = vehicleinfo.VehicleInfo()
        if self.params is None:
            frames = vinfo.options[self.vehicleinfo_key()]["frames"]
            self.params = frames[self.frame]["default_params_filename"]
        if not isinstance(self.params, list):
            self.params = [self.params]
        for x in self.params:
            self.mavproxy.send("param load %s\n" % os.path.join(testdir, x))
            self.mavproxy.expect('Loaded [0-9]+ parameters')
        self.set_parameter('LOG_REPLAY', 1)
        self.set_parameter('LOG_DISARMED', 1)
        self.reboot_sitl()
        self.fetch_parameters()

    def fetch_parameters(self):
        self.mavproxy.send("param fetch\n")
        self.mavproxy.expect("Received [0-9]+ parameters")

    def reboot_sitl(self):
        self.mavproxy.send("reboot\n")
        self.mavproxy.expect("tilt alignment complete")
        # empty mav to avoid getting old timestamps:
        if self.mav is not None:
            while self.mav.recv_match(blocking=False):
                pass
        # after reboot stream-rates may be zero.  Prompt MAVProxy to
        # send a rate-change message by changing away from our normal
        # stream rates and back again:
        if self.mav is not None:
            tstart = self.get_sim_time()
        while True:

            self.mavproxy.send("set streamrate %u\n" % (self.sitl_streamrate()*2))
            if self.mav is None:
                break

            if self.get_sim_time() - tstart > 10:
                raise AutoTestTimeoutException()

            m = self.mav.recv_match(type='SYSTEM_TIME',
                                    blocking=True,
                                    timeout=1)
            if m is not None:
                print("Received (%s)" % str(m))
                break
        self.mavproxy.send("set streamrate %u\n" % self.sitl_streamrate())
        self.progress("Reboot complete")

    def close(self):
        '''tidy up after running all tests'''
        if self.use_map:
            self.mavproxy.send("module unload map\n")
            self.mavproxy.expect("Unloaded module map")

        self.mav.close()
        util.pexpect_close(self.mavproxy)
        util.pexpect_close(self.sitl)

        valgrind_log = util.valgrind_log_filepath(binary=self.binary,
                                                  model=self.frame)
        if os.path.exists(valgrind_log):
            os.chmod(valgrind_log, 0o644)
            shutil.copy(valgrind_log,
                        self.buildlogs_path("%s-valgrind.log" %
                                            self.log_name))

    def start_test(self, description):
        self.progress("#")
        self.progress("########## %s  ##########" % description)
        self.progress("#")

    def try_symlink_tlog(self):
        self.buildlog = self.buildlogs_path(self.log_name + "-test.tlog")
        self.progress("buildlog=%s" % self.buildlog)
        if os.path.exists(self.buildlog):
            os.unlink(self.buildlog)
        try:
            os.link(self.logfile, self.buildlog)
        except OSError as error:
            self.progress("OSError [%d]: %s" % (error.errno, error.strerror))
            self.progress("WARN: Failed to create symlink: %s => %s, "
                          "will copy tlog manually to target location" %
                          (self.logfile, self.buildlog))
            self.copy_tlog = True

    #################################################
    # GENERAL UTILITIES
    #################################################
    def expect_list_clear(self):
        """clear the expect list."""
        global expect_list
        for p in expect_list[:]:
            expect_list.remove(p)

    def expect_list_extend(self, list_to_add):
        """Extend the expect list."""
        global expect_list
        expect_list.extend(list_to_add)

    def idle_hook(self, mav):
        """Called when waiting for a mavlink message."""
        global expect_list
        for p in expect_list:
            util.pexpect_drain(p)

    def message_hook(self, mav, msg):
        """Called as each mavlink msg is received."""
        self.idle_hook(mav)

    def expect_callback(self, e):
        """Called when waiting for a expect pattern."""
        global expect_list
        for p in expect_list:
            if p == e:
                continue
        util.pexpect_drain(p)

    #################################################
    # SIM UTILITIES
    #################################################
    def get_sim_time(self):
        """Get SITL time."""
        m = self.mav.recv_match(type='SYSTEM_TIME', blocking=True)
        return m.time_boot_ms * 1.0e-3

    def get_sim_time_cached(self):
        """Get SITL time."""
        x = self.mav.messages.get("SYSTEM_TIME", None)
        if x is None:
            return self.get_sim_time()
        return x.time_boot_ms * 1.0e-3

    def sim_location(self):
        """Return current simulator location."""
        m = self.mav.recv_match(type='SIMSTATE', blocking=True)
        return mavutil.location(m.lat*1.0e-7,
                                m.lng*1.0e-7,
                                0,
                                math.degrees(m.yaw))

    def save_wp(self):
        """Trigger RC 7 to save waypoint."""
        self.mavproxy.send('rc 7 1000\n')
        self.mav.recv_match(condition='RC_CHANNELS.chan7_raw==1000',
                            blocking=True)
        self.wait_seconds(1)
        self.mavproxy.send('rc 7 2000\n')
        self.mav.recv_match(condition='RC_CHANNELS.chan7_raw==2000',
                            blocking=True)
        self.wait_seconds(1)
        self.mavproxy.send('rc 7 1000\n')
        self.mav.recv_match(condition='RC_CHANNELS.chan7_raw==1000',
                            blocking=True)
        self.wait_seconds(1)

    def log_download(self, filename, timeout=360):
        """Download latest log."""
        self.disarm_vehicle()
        self.mav.wait_heartbeat()
        self.mavproxy.send("log list\n")
        self.mavproxy.expect("numLogs")
        self.mav.wait_heartbeat()
        self.mav.wait_heartbeat()
        self.mavproxy.send("set shownoise 0\n")
        self.mavproxy.send("log download latest %s\n" % filename)
        self.mavproxy.expect("Finished downloading", timeout=timeout)
        self.mav.wait_heartbeat()
        self.mav.wait_heartbeat()

    def show_gps_and_sim_positions(self, on_off):
        """Allow to display gps and actual position on map."""
        if on_off is True:
            # turn on simulator display of gps and actual position
            self.mavproxy.send('map set showgpspos 1\n')
            self.mavproxy.send('map set showsimpos 1\n')
        else:
            # turn off simulator display of gps and actual position
            self.mavproxy.send('map set showgpspos 0\n')
            self.mavproxy.send('map set showsimpos 0\n')

    @staticmethod
    def mission_count(filename):
        """Load a mission from a file and return number of waypoints."""
        wploader = mavwp.MAVWPLoader()
        wploader.load(filename)
        num_wp = wploader.count()
        return num_wp

    def load_mission_from_file(self, filename):
        """Load a mission from a file to flight controller."""
        self.mavproxy.send('wp load %s\n' % filename)
        self.mavproxy.expect('Flight plan received')
        self.mavproxy.send('wp list\n')
        self.mavproxy.expect('Requesting [0-9]+ waypoints')

        # update num_wp
        wploader = mavwp.MAVWPLoader()
        wploader.load(filename)
        num_wp = wploader.count()
        return num_wp

    def save_mission_to_file(self, filename):
        """Save a mission to a file"""
        self.mavproxy.send('wp save %s\n' % filename)
        self.mavproxy.expect('Saved ([0-9]+) waypoints')
        num_wp = int(self.mavproxy.match.group(1))
        self.progress("num_wp: %d" % num_wp)
        return num_wp

    def set_rc_default(self):
        """Setup all simulated RC control to 1500."""
        for chan in range(1, 16):
            self.mavproxy.send('rc %u 1500\n' % chan)

    def set_rc(self, chan, pwm, timeout=20):
        """Setup a simulated RC control to a PWM value"""
        tstart = self.get_sim_time()
        while self.get_sim_time_cached() < tstart + timeout:
            self.mavproxy.send('rc %u %u\n' % (chan, pwm))
            m = self.mav.recv_match(type='RC_CHANNELS', blocking=True)
            chan_pwm = getattr(m, "chan" + str(chan) + "_raw")
            if chan_pwm == pwm:
                return True
        self.progress("Failed to send RC commands to channel %s" % str(chan))
        raise SetRCTimeout()

    def set_throttle_zero(self):
        """Set throttle to zero."""
        if self.mav.mav_type == mavutil.mavlink.MAV_TYPE_GROUND_ROVER:
            self.set_rc(3, 1500)
        else:
            self.set_rc(3, 1000)

    def armed(self):
        '''Return true if vehicle is armed and safetyoff'''
        return self.mav.motors_armed()

    def arm_vehicle(self):
        """Arm vehicle with mavlink arm message."""
        self.mavproxy.send('arm throttle\n')
        self.mav.motors_armed_wait()
        self.progress("ARMED")
        return True

    def disarm_vehicle(self):
        """Disarm vehicle with mavlink disarm message."""
        self.mavproxy.send('disarm\n')
        self.mav.motors_disarmed_wait()
        self.progress("DISARMED")
        return True

    def arm_motors_with_rc_input(self):
        """Arm motors with radio."""
        self.progress("Arm motors with radio")
        self.set_throttle_zero()
        self.mavproxy.send('rc 1 2000\n')
        tstart = self.get_sim_time()
        timeout = 15
        while self.get_sim_time() < tstart + timeout:
            self.mav.wait_heartbeat()
            if not self.mav.motors_armed():
                arm_delay = self.get_sim_time() - tstart
                self.progress("MOTORS ARMED OK WITH RADIO")
                self.mavproxy.send('rc 1 1500\n')
                self.progress("Arm in %ss" % arm_delay)  # TODO check arming time
                return True
        self.progress("FAILED TO ARM WITH RADIO")
        self.mavproxy.send('rc 1 1500\n')
        return False

    def disarm_motors_with_rc_input(self):
        """Disarm motors with radio."""
        self.progress("Disarm motors with radio")
        self.set_throttle_zero()
        self.mavproxy.send('rc 1 1000\n')
        tstart = self.get_sim_time()
        timeout = 15
        while self.get_sim_time() < tstart + timeout:
            self.mav.wait_heartbeat()
            if not self.mav.motors_armed():
                disarm_delay = self.get_sim_time() - tstart
                self.progress("MOTORS DISARMED OK WITH RADIO")
                self.mavproxy.send('rc 1 1500\n')
                self.progress("Disarm in %ss" % disarm_delay)  # TODO check disarming time
                return True
        self.progress("FAILED TO DISARM WITH RADIO")
        self.mavproxy.send('rc 1 1500\n')
        return False

    def autodisarm_motors(self):
        """Autodisarm motors."""
        self.progress("Autodisarming motors")
        self.set_throttle_zero()
        if self.mav.mav_type == mavutil.mavlink.MAV_TYPE_GROUND_ROVER:  # NOT IMPLEMENTED ON ROVER
            self.progress("MOTORS AUTODISARMED OK")
            return True
        tstart = self.get_sim_time()
        timeout = 15
        while self.get_sim_time() < tstart + timeout:
            self.mav.wait_heartbeat()
            if not self.mav.motors_armed():
                disarm_delay = self.get_sim_time() - tstart
                self.progress("MOTORS AUTODISARMED")
                self.progress("Autodisarm in %ss" % disarm_delay)  # TODO check disarming time
                return True
        self.progress("FAILED TO AUTODISARM")
        return False

    def set_parameter(self, name, value, add_to_context=True):
        old_value = self.get_parameter(name, retry=2)
        for i in range(1, 10):
            self.mavproxy.send("param set %s %s\n" % (name, str(value)))
            returned_value = self.get_parameter(name)
            if returned_value == float(value):
                # yes, exactly equal.
                if add_to_context:
                    self.context_get().parameters.append( (name, old_value) )
                return
            self.progress("Param fetch returned incorrect value (%s) vs (%s)"
                          % (returned_value, value))
        raise ValueError()

    def get_parameter(self, name, retry=1, timeout=60):
        for i in range(0, retry):
            self.mavproxy.send("param fetch %s\n" % name)
            try:
                self.mavproxy.expect("%s = ([-0-9.]*)\r\n" % (name,), timeout=timeout/retry)
                return float(self.mavproxy.match.group(1))
            except pexpect.TIMEOUT:
                if i < retry:
                    continue

    def context_get(self):
        return self.contexts[-1]

    def context_push(self):
        self.contexts.append(Context())

    def context_pop(self):
        dead = self.contexts.pop()

        '''set paramters to origin values in reverse order'''
        dead_parameters = dead.parameters
        dead_parameters.reverse()
        for p in dead_parameters:
            (name, old_value) = p
            self.set_parameter(name,
                               old_value,
                               add_to_context=False)

    def run_cmd(self,
                command,
                p1,
                p2,
                p3,
                p4,
                p5,
                p6,
                p7,
                want_result=mavutil.mavlink.MAV_RESULT_ACCEPTED):
        self.mav.mav.command_long_send(1,
                                       1,
                                       command,
                                       1,  # confirmation
                                       p1,
                                       p2,
                                       p3,
                                       p4,
                                       p5,
                                       p6,
                                       p7)
        while True:
            m = self.mav.recv_match(type='COMMAND_ACK', blocking=True)
            self.progress("ACK received: %s" % str(m))
            if m.command == command:
                if m.result != want_result:
                    raise ValueError()
                break

    #################################################
    # UTILITIES
    #################################################
    @staticmethod
    def get_distance(loc1, loc2):
        """Get ground distance between two locations."""
        dlat = loc2.lat - loc1.lat
        try:
            dlong = loc2.lng - loc1.lng
        except AttributeError:
            dlong = loc2.lon - loc1.lon

        return math.sqrt((dlat*dlat) + (dlong*dlong)) * 1.113195e5

    @staticmethod
    def get_distance_int(loc1, loc2):
        """Get ground distance between two locations in the normal "int" form
        - lat/lon multiplied by 1e7"""
        dlat = loc2.lat - loc1.lat
        try:
            dlong = loc2.lng - loc1.lng
        except AttributeError:
            dlong = loc2.lon - loc1.lon

        dlat /= 10000000.0
        dlong /= 10000000.0

        return math.sqrt((dlat*dlat) + (dlong*dlong)) * 1.113195e5

    @staticmethod
    def get_bearing(loc1, loc2):
        """Get bearing from loc1 to loc2."""
        off_x = loc2.lng - loc1.lng
        off_y = loc2.lat - loc1.lat
        bearing = 90.00 + math.atan2(-off_y, off_x) * 57.2957795
        if bearing < 0:
            bearing += 360.00
        return bearing

    def do_get_autopilot_capabilities(self):
        self.mavproxy.send("long REQUEST_AUTOPILOT_CAPABILITIES 1\n")
        m = self.mav.recv_match(type='AUTOPILOT_VERSION',
                                blocking=True,
                                timeout=10)
        if m is None:
            self.progress("AUTOPILOT_VERSION not received")
            raise NotAchievedException()
        self.progress("AUTOPILOT_VERSION received")

    def do_set_mode_via_command_long(self):
        base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        custom_mode = 4  # hold
        start = time.time()
        while time.time() - start < 5:
            self.mavproxy.send("long DO_SET_MODE %u %u\n" %
                               (base_mode, custom_mode))
            m = self.mav.recv_match(type='HEARTBEAT',
                                    blocking=True,
                                    timeout=10)
            if m is None:
                raise ErrorException()
            if m.custom_mode == custom_mode:
                return
            time.sleep(0.1)
        raise AutoTestTimeoutException()

    def reach_heading_manual(self, heading):
        """Manually direct the vehicle to the target heading."""
        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                 mavutil.mavlink.MAV_TYPE_HELICOPTER,
                                 mavutil.mavlink.MAV_TYPE_HEXAROTOR,
                                 mavutil.mavlink.MAV_TYPE_OCTOROTOR,
                                 mavutil.mavlink.MAV_TYPE_COAXIAL,
                                 mavutil.mavlink.MAV_TYPE_TRICOPTER]:
            self.mavproxy.send('rc 4 1580\n')
            self.wait_heading(heading)
            self.mavproxy.send('rc 4 1500\n')
            self.mav.recv_match(condition='RC_CHANNELS.chan4_raw==1500',
                                blocking=True)
        if self.mav.mav_type == mavutil.mavlink.MAV_TYPE_FIXED_WING:
            self.progress("NOT IMPLEMENTED")
        if self.mav.mav_type == mavutil.mavlink.MAV_TYPE_GROUND_ROVER:
            self.mavproxy.send('rc 1 1700\n')
            self.mavproxy.send('rc 3 1550\n')
            self.wait_heading(heading)
            self.mavproxy.send('rc 3 1500\n')
            self.mav.recv_match(condition='RC_CHANNELS.chan3_raw==1500',
                                blocking=True)
            self.mavproxy.send('rc 1 1500\n')
            self.mav.recv_match(condition='RC_CHANNELS.chan1_raw==1500',
                                blocking=True)

    def reach_distance_manual(self,  distance):
        """Manually direct the vehicle to the target distance from home."""
        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                 mavutil.mavlink.MAV_TYPE_HELICOPTER,
                                 mavutil.mavlink.MAV_TYPE_HEXAROTOR,
                                 mavutil.mavlink.MAV_TYPE_OCTOROTOR,
                                 mavutil.mavlink.MAV_TYPE_COAXIAL,
                                 mavutil.mavlink.MAV_TYPE_TRICOPTER]:
            self.mavproxy.send('rc 2 1350\n')
            self.wait_distance(distance, accuracy=5, timeout=60)
            self.mavproxy.send('rc 2 1500\n')
            self.mav.recv_match(condition='RC_CHANNELS.chan2_raw==1500',
                                blocking=True)
        if self.mav.mav_type == mavutil.mavlink.MAV_TYPE_FIXED_WING:
            self.progress("NOT IMPLEMENTED")
        if self.mav.mav_type == mavutil.mavlink.MAV_TYPE_GROUND_ROVER:
            self.mavproxy.send('rc 3 1700\n')
            self.wait_distance(distance, accuracy=2)
            self.mavproxy.send('rc 3 1500\n')
            self.mav.recv_match(condition='RC_CHANNELS.chan3_raw==1500',
                                blocking=True)

    def guided_achieve_heading(self, heading):
        tstart = self.get_sim_time()
        self.run_cmd(mavutil.mavlink.MAV_CMD_CONDITION_YAW,
                     heading,  # target angle
                     10,  # degrees/second
                     1,  # -1 is counter-clockwise, 1 clockwise
                     0,  # 1 for relative, 0 for absolute
                     0,  # p5
                     0,  # p6
                     0,  # p7
                     )
        while True:
            if self.get_sim_time() - tstart > 200:
                raise NotAchievedException()
            m = self.mav.recv_match(type='VFR_HUD', blocking=True)
            self.progress("heading=%f want=%f" % (m.heading, heading))
            if m.heading == heading:
                return

    #################################################
    # WAIT UTILITIES
    #################################################
    def wait_seconds(self, seconds_to_wait):
        """Wait some second in SITL time."""
        tstart = self.get_sim_time()
        tnow = tstart
        while tstart + seconds_to_wait > tnow:
            tnow = self.get_sim_time()

    def wait_altitude(self, alt_min, alt_max, timeout=30, relative=False):
        """Wait for a given altitude range."""
        climb_rate = 0
        previous_alt = 0

        tstart = self.get_sim_time()
        self.progress("Waiting for altitude between %u and %u" %
                      (alt_min, alt_max))
        while self.get_sim_time() < tstart + timeout:
            m = self.mav.recv_match(type='GLOBAL_POSITION_INT', blocking=True)
            if m is None:
                continue
            if relative:
                alt = m.relative_alt/1000.0 # mm -> m
            else:
                alt = m.alt/1000.0 # mm -> m

            climb_rate = alt - previous_alt
            previous_alt = alt
            self.progress("Wait Altitude: Cur:%u, min_alt:%u, climb_rate: %u"
                          % (alt, alt_min, climb_rate))
            if alt >= alt_min and alt <= alt_max:
                self.progress("Altitude OK")
                return True
        self.progress("Failed to attain altitude range")
        raise WaitAltitudeTimout()

    def wait_groundspeed(self, gs_min, gs_max, timeout=30):
        """Wait for a given ground speed range."""
        tstart = self.get_sim_time()
        self.progress("Waiting for groundspeed between %.1f and %.1f" %
                      (gs_min, gs_max))
        while self.get_sim_time() < tstart + timeout:
            m = self.mav.recv_match(type='VFR_HUD', blocking=True)
            self.progress("Wait groundspeed %.1f, target:%.1f" %
                          (m.groundspeed, gs_min))
            if m.groundspeed >= gs_min and m.groundspeed <= gs_max:
                return True
        self.progress("Failed to attain groundspeed range")
        raise WaitGroundSpeedTimeout()

    def wait_roll(self, roll, accuracy, timeout=30):
        """Wait for a given roll in degrees."""
        tstart = self.get_sim_time()
        self.progress("Waiting for roll of %d at %s" % (roll, time.ctime()))
        while self.get_sim_time() < tstart + timeout:
            m = self.mav.recv_match(type='ATTITUDE', blocking=True)
            p = math.degrees(m.pitch)
            r = math.degrees(m.roll)
            self.progress("Roll %d Pitch %d" % (r, p))
            if math.fabs(r - roll) <= accuracy:
                self.progress("Attained roll %d" % roll)
                return True
        self.progress("Failed to attain roll %d" % roll)
        raise WaitRollTimeout()

    def wait_pitch(self, pitch, accuracy, timeout=30):
        """Wait for a given pitch in degrees."""
        tstart = self.get_sim_time()
        self.progress("Waiting for pitch of %u at %s" % (pitch, time.ctime()))
        while self.get_sim_time() < tstart + timeout:
            m = self.mav.recv_match(type='ATTITUDE', blocking=True)
            p = math.degrees(m.pitch)
            r = math.degrees(m.roll)
            self.progress("Pitch %d Roll %d" % (p, r))
            if math.fabs(p - pitch) <= accuracy:
                self.progress("Attained pitch %d" % pitch)
                return True
        self.progress("Failed to attain pitch %d" % pitch)
        raise WaitPitchTimeout()

    def wait_heading(self, heading, accuracy=5, maintain_target_time=0, timeout=30, the_function=None):
        """Wait for a given heading."""
        tstart = self.get_sim_time()
        duration_start = None
        mean_heading = 0.0
        last_heading = 0.0
        counter = 0.0
        self.progress("Waiting for heading %u with accuracy %u" %
                      (heading, accuracy))
        while self.get_sim_time() < tstart + timeout:
            if the_function is not None:
                the_function()
            m = self.mav.recv_match(type='VFR_HUD', blocking=True)
            last_heading = m.heading
            if math.fabs(last_heading - heading) <= accuracy or heading <= accuracy and math.fabs(m.heading - 360) <= accuracy:
                mean_heading += last_heading
                counter += 1.0
                if duration_start is None:
                    duration_start = self.get_sim_time()
                if self.get_sim_time() - duration_start > maintain_target_time:
                    if heading >= accuracy:
                        self.progress("Attained heading %f" % (mean_heading / counter))
                    else:
                        self.progress("Attained heading %f" % m.heading)
                    return True
            else:
                duration_start = None
                mean_heading = 0.0
                counter = 0.0
        self.progress("Failed to attain heading %u, reach %f" % (heading, (mean_heading / counter) if mean_heading != 0.0 else last_heading))
        raise WaitHeadingTimeout()

    def wait_yaw_speed(self, target_yaw_speed, target_accuracy=0.2, maintain_target_time=5, timeout=30, the_function=None):
        """Wait for a given yaw speed in degrees."""
        tstart = self.get_sim_time()
        duration_start = None
        mean_yaw_rate = 0.0
        last_yaw_rate = 0.0
        counter = 0.0
        self.progress("Waiting for yaw speed of %d" % target_yaw_speed)
        while self.get_sim_time() < tstart + timeout:
            if the_function is not None:
                the_function()
            m = self.mav.recv_match(type='ATTITUDE', blocking=True)
            last_yaw_rate = math.degrees(m.yawspeed)
            if math.fabs(last_yaw_rate - target_yaw_speed) <= target_accuracy:
                mean_yaw_rate += last_yaw_rate
                counter += 1.0
                if duration_start is None:
                    duration_start = self.get_sim_time()
                if self.get_sim_time() - duration_start > maintain_target_time:
                    self.progress("Attained yaw speed %f" % (mean_yaw_rate / counter))
                    return True
            else:
                duration_start = None
                mean_yaw_rate = 0.0
                counter = 0.0
        self.progress("Failed to attain yaw speed expect %f, reach %f" % (target_yaw_speed, (mean_yaw_rate / counter) if mean_yaw_rate != 0.0 else last_yaw_rate))
        raise YawSpeedNotAchievedException()

    def wait_speed_vector(self, target_vx, target_vy, target_vz, target_accuracy=0.2, maintain_target_time=5, timeout=30, the_function=None):  # todo improve to be able to pass only one target
        """Wait for a given speed vector."""
        tstart = self.get_sim_time()
        duration_start = None
        mean_vx = 0.0
        mean_vy = 0.0
        mean_vz = 0.0
        counter = 0.0
        self.progress("Waiting for speed vector of %f, %f, %f" % (target_vx, target_vy, target_vz))
        while self.get_sim_time() < tstart + timeout:
            if the_function is not None:
                the_function()
            m = self.mav.recv_match(type='LOCAL_POSITION_NED', blocking=True)
            if math.fabs(m.vx - target_vx) <= target_accuracy and math.fabs(m.vy - target_vy) <= target_accuracy and math.fabs(m.vz - target_vz) <= target_accuracy:
                mean_vx += m.vx
                mean_vy += m.vy
                mean_vz += m.vz
                counter += 1.0
                if duration_start is None:
                    duration_start = self.get_sim_time()
                if self.get_sim_time() - duration_start > maintain_target_time:
                    self.progress("Attained speed vector %f, %f, %f" % (mean_vx / counter, mean_vy / counter, mean_vz / counter))
                    return True
            else:
                duration_start = None
                mean_vx = 0.0
                mean_vy = 0.0
                mean_vz = 0.0
                counter = 0.0
        self.progress("Failed to attain speed vector %f, %f, %f" % (target_vx, target_vy, target_vz))
        raise SpeedVectorNotAchievedException()

    def wait_distance(self, distance, accuracy=5, timeout=30):
        """Wait for flight of a given distance."""
        tstart = self.get_sim_time()
        start = self.mav.location()
        while self.get_sim_time() < tstart + timeout:
            pos = self.mav.location()
            delta = self.get_distance(start, pos)
            self.progress("Distance %.2f meters" % delta)
            if math.fabs(delta - distance) <= accuracy:
                self.progress("Attained distance %.2f meters OK" % delta)
                return True
            if delta > (distance + accuracy):
                self.progress("Failed distance - overshoot delta=%f dist=%f"
                              % (delta, distance))
                raise WaitDistanceTimeout()
        self.progress("Failed to attain distance %u" % distance)
        raise WaitDistanceTimeout()

    def wait_servo_channel_value(self, channel, value, timeout=2):
        """wait for channel to hit value"""
        channel_field = "servo%u_raw" % channel
        tstart = self.get_sim_time()
        while True:
            remaining = timeout - (self.get_sim_time_cached() - tstart)
            if remaining <= 0:
                raise NotAchievedException()
            m = self.mav.recv_match(type='SERVO_OUTPUT_RAW',
                                    blocking=True,
                                    timeout=remaining)
            m_value = getattr(m, channel_field, None)
            self.progress("SERVO_OUTPUT_RAW.%s=%u want=%u" %
                          (channel_field, m_value, value))
            if m_value is None:
                raise ValueError() #?
            if m_value == value:
                return

    def wait_location(self,
                      loc,
                      accuracy=5.0,
                      timeout=30,
                      target_altitude=None,
                      height_accuracy=-1):
        """Wait for arrival at a location."""
        tstart = self.get_sim_time()
        if target_altitude is None:
            target_altitude = loc.alt
        self.progress("Waiting for location "
                      "%.4f,%.4f at altitude %.1f height_accuracy=%.1f" %
                      (loc.lat, loc.lng, target_altitude, height_accuracy))
        while self.get_sim_time() < tstart + timeout:
            pos = self.mav.location()
            delta = self.get_distance(loc, pos)
            self.progress("Distance %.2f meters alt %.1f" % (delta, pos.alt))
            if delta <= accuracy:
                height_delta = math.fabs(pos.alt - target_altitude)
                if (height_accuracy != -1 and height_delta > height_accuracy):
                    continue
                self.progress("Reached location (%.2f meters)" % delta)
                return True
        self.progress("Failed to attain location")
        raise WaitLocationTimeout()

    def wait_waypoint(self,
                      wpnum_start,
                      wpnum_end,
                      allow_skip=True,
                      max_dist=2,
                      timeout=400):
        """Wait for waypoint ranges."""
        tstart = self.get_sim_time()
        # this message arrives after we set the current WP
        start_wp = self.mav.waypoint_current()
        current_wp = start_wp
        mode = self.mav.flightmode

        self.progress("\nWait for waypoint ranges start=%u end=%u\n\n"
                      % (wpnum_start, wpnum_end))
        # if start_wp != wpnum_start:
        #    self.progress("test: Expected start waypoint %u but got %u" %
        #                  (wpnum_start, start_wp))
        #    raise WaitWaypointTimeout()
        last_wp_dist = 0.0
        last_alt = 0.0
        while self.get_sim_time() < tstart + timeout:
            seq = self.mav.waypoint_current()
            m = self.mav.recv_match(type='NAV_CONTROLLER_OUTPUT',
                                    blocking=True)
            wp_dist = m.wp_dist
            m = self.mav.recv_match(type='VFR_HUD', blocking=True)
            current_alt = m.alt
            # if we changed mode, fail
            if self.mav.flightmode != mode:
                self.progress('Exited %s mode' % mode)
                raise WaitWaypointTimeout()
            if wp_dist != last_wp_dist or current_alt != last_alt:
                self.progress("WP %u (wp_dist=%u Alt=%d), current_wp: %u,"
                              "wpnum_end: %u" %
                              (seq, wp_dist, current_alt, current_wp, wpnum_end))
                last_wp_dist = wp_dist
                last_alt = current_alt
            if seq == current_wp+1 or (seq > current_wp+1 and allow_skip):
                self.progress("Starting new waypoint %u" % seq)
                tstart = self.get_sim_time()
                current_wp = seq
                # the wp_dist check is a hack until we can sort out
                # the right seqnum for end of mission
            # if current_wp == wpnum_end or (current_wp == wpnum_end-1 and
            #                                wp_dist < 2):
            if current_wp == wpnum_end and wp_dist < max_dist:
                self.progress("Reached final waypoint %u" % seq)
                return True
            if seq >= 255:
                self.progress("Reached final waypoint %u" % seq)
                return True
            if seq > current_wp+1:
                self.progress("Failed: Skipped waypoint! Got wp %u expected %u"
                              % (seq, current_wp+1))
                raise WaitWaypointTimeout()
        self.progress("Failed: Timed out waiting for waypoint %u of %u" %
                      (wpnum_end, wpnum_end))
        raise WaitWaypointTimeout()

    def wait_mode(self, mode, timeout=60):
        """Wait for mode to change."""
        mode_map = self.mav.mode_mapping()
        if mode_map is None or mode not in mode_map:
            self.progress("Unknown mode '%s'" % mode)
            self.progress("Available modes '%s'" % mode_map.keys())
            raise ErrorException()
        self.progress("Waiting for mode %s" % mode)
        tstart = self.get_sim_time()
        self.mav.wait_heartbeat()
        while self.mav.flightmode != mode:
            if (timeout is not None and
                self.get_sim_time() > tstart + timeout):
                raise WaitModeTimeout()
            self.mav.wait_heartbeat()
#            self.progress("heartbeat mode %s Want: %s" % (
#                    self.mav.flightmode, mode))
        self.progress("Got mode %s" % mode)

    def wait_ready_to_arm(self, timeout=None):
        # wait for EKF checks to pass
        self.progress("Waiting reading for arm")
        return self.wait_ekf_happy(timeout=timeout)

    def wait_ekf_happy(self, timeout=30):
        """Wait for EKF to be happy"""

        """ if using SITL estimates directly """
        if (int(self.get_parameter('AHRS_EKF_TYPE')) == 10):
            return True

        tstart = self.get_sim_time()
        # all of these must be set for arming to happen:
        required_value = (mavutil.mavlink.EKF_ATTITUDE |
                          mavutil.mavlink.ESTIMATOR_VELOCITY_HORIZ |
                          mavutil.mavlink.ESTIMATOR_VELOCITY_VERT |
                          mavutil.mavlink.ESTIMATOR_POS_HORIZ_REL |
                          mavutil.mavlink.ESTIMATOR_POS_HORIZ_ABS |
                          mavutil.mavlink.ESTIMATOR_POS_VERT_ABS |
                          mavutil.mavlink.ESTIMATOR_PRED_POS_HORIZ_REL |
                          mavutil.mavlink.ESTIMATOR_PRED_POS_HORIZ_ABS)
        # none of these bits must be set for arming to happen:
        error_bits = (mavutil.mavlink.ESTIMATOR_CONST_POS_MODE |
                      mavutil.mavlink.ESTIMATOR_GPS_GLITCH |
                      mavutil.mavlink.ESTIMATOR_ACCEL_ERROR)
        self.progress("Waiting for EKF value %u" % required_value)
        while timeout is None or self.get_sim_time() < tstart + timeout:
            m = self.mav.recv_match(type='EKF_STATUS_REPORT', blocking=True)
            current = m.flags
            if (tstart - self.get_sim_time()) % 5 == 0:
                self.progress("Wait EKF.flags: required:%u current:%u" %
                              (required_value, current))
            errors = current & error_bits
            if errors:
                self.progress("Wait EKF.flags: errors=%u" % errors)
                continue
            if (current & required_value == required_value):
                self.progress("EKF Flags OK")
                return True
        self.progress("Failed to get EKF.flags=%u" % required_value)
        raise AutoTestTimeoutException()

    def get_mavlink_connection_going(self):
        # get a mavlink connection going
        connection_string = self.autotest_connection_string_to_mavproxy()
        try:
            self.mav = mavutil.mavlink_connection(connection_string,
                                                  robust_parsing=True,
                                                  source_component=250)
        except Exception as msg:
            self.progress("Failed to start mavlink connection on %s: %s" %
                          (connection_string, msg,))
            raise
        self.mav.message_hooks.append(self.message_hook)
        self.mav.idle_hooks.append(self.idle_hook)

    def run_test(self, desc, function, interact=False):
        self.start_test(desc)

        try:
            function()
        except Exception as e:
            self.progress('FAILED: "%s": %s' % (desc, repr(e)))
            self.fail_list.append((desc, e))
            if interact:
                self.progress("Starting MAVProxy interaction as directed")
                self.mavproxy.interact()
            return
        self.progress('PASSED: "%s"' % desc)

    def check_test_syntax(self, test_file):
        """Check mistake on autotest function syntax."""
        import re
        self.start_test("Check for syntax mistake in autotest lambda")
        if not os.path.isfile(test_file):
            self.progress("File %s does not exist" % test_file)
        test_file = test_file.rstrip('c')
        try:
            with open(test_file) as f:
                # check for lambda: test_function without paranthesis
                faulty_strings = re.findall(r"lambda\s*:\s*\w+.\w+\s*\)", f.read())
                if faulty_strings:
                    self.progress("Syntax error in autotest lamda at : ")
                    print(faulty_strings)
                    raise ErrorException()
        except ErrorException:
            self.progress('FAILED: "%s"' % "Check for syntax mistake in autotest lambda")
            exit(1)
        self.progress('PASSED: "%s"' % "Check for syntax mistake in autotest lambda")

    @abc.abstractmethod
    def init(self):
        """Initilialize autotest feature."""
        pass

    def test_arm_feature(self):
        """Common feature to test."""
        # TEST ARMING/DISARM
        if not self.arm_vehicle():
            self.progress("Failed to ARM")
            raise NotAchievedException()
        if not self.disarm_vehicle():
            self.progress("Failed to DISARM")
            raise NotAchievedException()
        if not self.arm_motors_with_rc_input():
            raise NotAchievedException()
        if not self.disarm_motors_with_rc_input():
            raise NotAchievedException()
        if not self.autodisarm_motors():
            raise NotAchievedException()
        # TODO : add failure test : arming check, wrong mode; Test arming magic; Same for disarm

    def test_set_position_global_int(self, test_alt=True, test_heading=False, test_yaw_rate=False, timeout=100):
        """Test set position message in guided mode."""
        self.set_parameter("FS_GCS_ENABLE", 0)
        self.set_throttle_zero()
        self.mavproxy.send('mode guided\n')
        self.wait_mode('GUIDED')
        self.wait_ready_to_arm()
        self.arm_vehicle()

        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                 mavutil.mavlink.MAV_TYPE_HELICOPTER,
                                 mavutil.mavlink.MAV_TYPE_HEXAROTOR,
                                 mavutil.mavlink.MAV_TYPE_OCTOROTOR,
                                 mavutil.mavlink.MAV_TYPE_COAXIAL,
                                 mavutil.mavlink.MAV_TYPE_TRICOPTER,
                                 mavutil.mavlink.MAV_TYPE_SUBMARINE]:
            self.user_takeoff(alt_min=50)

        targetpos = self.mav.location()
        wp_accuracy = None
        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                 mavutil.mavlink.MAV_TYPE_HELICOPTER,
                                 mavutil.mavlink.MAV_TYPE_HEXAROTOR,
                                 mavutil.mavlink.MAV_TYPE_OCTOROTOR,
                                 mavutil.mavlink.MAV_TYPE_COAXIAL,
                                 mavutil.mavlink.MAV_TYPE_TRICOPTER,
                                 mavutil.mavlink.MAV_TYPE_SUBMARINE]:
            wp_accuracy = self.get_parameter("WPNAV_RADIUS", retry=2)
            wp_accuracy = wp_accuracy * 0.01  # cm to m
        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_FIXED_WING,
                                 mavutil.mavlink.MAV_TYPE_GROUND_ROVER,
                                 mavutil.mavlink.MAV_TYPE_SURFACE_BOAT]:
            wp_accuracy = self.get_parameter("WP_RADIUS", retry=2)
        if wp_accuracy is None:
            raise ValueError()

        def to_alt_frame(alt, mav_frame):
            if mav_frame in ["MAV_FRAME_GLOBAL_RELATIVE_ALT",
                              "MAV_FRAME_GLOBAL_RELATIVE_ALT_INT",
                              "MAV_FRAME_GLOBAL_TERRAIN_ALT",
                              "MAV_FRAME_GLOBAL_TERRAIN_ALT_INT"]:
                return alt - self.homeloc.alt
            else:
                return alt

        def send_target_position(lat, lng, alt, mav_frame):
            self.mav.mav.set_position_target_global_int_send(
                0,  # timestamp
                1,  # target system_id
                1,  # target component id
                mav_frame,
                MAVLINK_SET_POS_TYPE_MASK_VEL_IGNORE |
                MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                MAVLINK_SET_POS_TYPE_MASK_FORCE |
                MAVLINK_SET_POS_TYPE_MASK_YAW_IGNORE |
                MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                lat * 1.0e7,  # lat
                lng * 1.0e7,  # lon
                alt,  # alt
                0,  # vx
                0,  # vy
                0,  # vz
                0,  # afx
                0,  # afy
                0,  # afz
                0,  # yaw
                0,  # yawrate
            )
        for frame_name, frame in MAV_FRAMES.items():
            self.start_test("Testing Set Position in %s" % frame_name)

            targetpos.lat += 0.0001
            if test_alt:
                targetpos.alt += 5
            send_target_position(targetpos.lat, targetpos.lng, to_alt_frame(targetpos.alt, frame_name), frame)
            if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                      target_altitude=(targetpos.alt if test_alt else None),
                                      height_accuracy=2):
                raise NotAchievedException()

            targetpos.lng += 0.0001
            if test_alt:
                targetpos.alt -= 5
            send_target_position(targetpos.lat, targetpos.lng, to_alt_frame(targetpos.alt, frame_name), frame)
            if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                      target_altitude=(targetpos.alt if test_alt else None),
                                      height_accuracy=2):
                raise NotAchievedException()

            targetpos.lat -= 0.0001
            if test_alt:
                targetpos.alt += 5
            send_target_position(targetpos.lat, targetpos.lng, to_alt_frame(targetpos.alt, frame_name), frame)
            if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                      target_altitude=(targetpos.alt if test_alt else None),
                                      height_accuracy=2):
                raise NotAchievedException()

            targetpos.lng -= 0.0001
            if test_alt:
                targetpos.alt -= 5
            send_target_position(targetpos.lat, targetpos.lng, to_alt_frame(targetpos.alt, frame_name), frame)
            if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                      target_altitude=(targetpos.alt if test_alt else None),
                                      height_accuracy=2):
                raise NotAchievedException()

            targetpos.lng += 0.0001
            if test_alt:
                targetpos.alt += 5
            send_target_position(targetpos.lat, targetpos.lng, to_alt_frame(targetpos.alt, frame_name), frame)
            if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                      target_altitude=(targetpos.alt if test_alt else None),
                                      height_accuracy=2):
                raise NotAchievedException()

            targetpos.lng -= 0.0001
            if test_alt:
                targetpos.alt -= 5
            send_target_position(targetpos.lat, targetpos.lng, to_alt_frame(targetpos.alt, frame_name), frame)
            if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                      target_altitude=(targetpos.alt if test_alt else None),
                                      height_accuracy=2):
                raise NotAchievedException()

            if test_heading:
                self.start_test("Testing Yaw targetting in %s" % frame_name)

                targetpos.lat += 0.0001
                if test_alt:
                    targetpos.alt += 5
                self.mav.mav.set_position_target_global_int_send(
                    0,  # timestamp
                    1,  # target system_id
                    1,  # target component id
                    frame,
                    MAVLINK_SET_POS_TYPE_MASK_VEL_IGNORE |
                    MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                    MAVLINK_SET_POS_TYPE_MASK_FORCE |
                    MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                    targetpos.lat * 1.0e7,  # lat
                    targetpos.lng * 1.0e7,  # lon
                    to_alt_frame(targetpos.alt, frame_name),  # alt
                    0,  # vx
                    0,  # vy
                    0,  # vz
                    0,  # afx
                    0,  # afy
                    0,  # afz
                    math.radians(42),  # yaw
                    0,  # yawrate
                )
                if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                          target_altitude=(targetpos.alt if test_alt else None),
                                          height_accuracy=2):
                    raise NotAchievedException()
                if not self.wait_heading(42, maintain_target_time=5, timeout=timeout):
                    raise NotAchievedException()

                targetpos.lat -= 0.0001
                if test_alt:
                    targetpos.alt -= 5
                self.mav.mav.set_position_target_global_int_send(
                    0,  # timestamp
                    1,  # target system_id
                    1,  # target component id
                    frame,
                    MAVLINK_SET_POS_TYPE_MASK_VEL_IGNORE |
                    MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                    MAVLINK_SET_POS_TYPE_MASK_FORCE |
                    MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                    targetpos.lat * 1.0e7,  # lat
                    targetpos.lng * 1.0e7,  # lon
                    to_alt_frame(targetpos.alt, frame_name),  # alt
                    0,  # vx
                    0,  # vy
                    0,  # vz
                    0,  # afx
                    0,  # afy
                    0,  # afz
                    math.radians(0),  # yaw
                    0,  # yawrate
                )
                if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                          target_altitude=(targetpos.alt if test_alt else None),
                                          height_accuracy=2):
                    raise NotAchievedException()
                if not self.wait_heading(0, maintain_target_time=5, timeout=timeout):
                    raise NotAchievedException()

            if test_yaw_rate:
                self.start_test("Testing Yaw Rate targetting in %s" % frame_name)

                def send_yaw_rate(rate):
                    self.mav.mav.set_position_target_global_int_send(
                        0,  # timestamp
                        1,  # target system_id
                        1,  # target component id
                        frame,
                        MAVLINK_SET_POS_TYPE_MASK_VEL_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_FORCE |
                        MAVLINK_SET_POS_TYPE_MASK_YAW_IGNORE,
                        targetpos.lat * 1.0e7,  # lat
                        targetpos.lng * 1.0e7,  # lon
                        to_alt_frame(targetpos.alt, frame_name),  # alt
                        0,  # vx
                        0,  # vy
                        0,  # vz
                        0,  # afx
                        0,  # afy
                        0,  # afz
                        0,  # yaw
                        rate,  # yawrate
                    )

                target_rate = 1.0
                targetpos.lat += 0.0001
                if test_alt:
                    targetpos.alt += 5
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate(math.radians(target_rate))):
                    raise NotAchievedException()
                if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                          target_altitude=(targetpos.alt if test_alt else None),
                                          height_accuracy=2):
                    raise NotAchievedException()

                target_rate = -1.0
                targetpos.lat -= 0.0001
                if test_alt:
                    targetpos.alt -= 5
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate(math.radians(target_rate))):
                    raise NotAchievedException()
                if not self.wait_location(targetpos, accuracy=wp_accuracy, timeout=timeout,
                                          target_altitude=(targetpos.alt if test_alt else None),
                                          height_accuracy=2):
                    raise NotAchievedException()

                target_rate = 0.0
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate(math.radians(target_rate))):
                    raise NotAchievedException()

    def test_set_velocity_global_int(self, test_vz=True, test_heading=False, test_yaw_rate=False, timeout=30):
        """Test set position message in guided mode."""
        self.set_parameter("FS_GCS_ENABLE", 0)
        self.set_throttle_zero()
        self.mavproxy.send('mode guided\n')
        self.wait_mode('GUIDED')
        self.wait_ready_to_arm()
        self.arm_vehicle()

        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                 mavutil.mavlink.MAV_TYPE_HELICOPTER,
                                 mavutil.mavlink.MAV_TYPE_HEXAROTOR,
                                 mavutil.mavlink.MAV_TYPE_OCTOROTOR,
                                 mavutil.mavlink.MAV_TYPE_COAXIAL,
                                 mavutil.mavlink.MAV_TYPE_TRICOPTER,
                                 mavutil.mavlink.MAV_TYPE_SUBMARINE]:
            self.user_takeoff(alt_min=50)

        target_vx = 1.0
        target_vy = 0.0
        target_vz = 0.0
        wp_accuracy = None
        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                 mavutil.mavlink.MAV_TYPE_HELICOPTER,
                                 mavutil.mavlink.MAV_TYPE_HEXAROTOR,
                                 mavutil.mavlink.MAV_TYPE_OCTOROTOR,
                                 mavutil.mavlink.MAV_TYPE_COAXIAL,
                                 mavutil.mavlink.MAV_TYPE_TRICOPTER,
                                 mavutil.mavlink.MAV_TYPE_SUBMARINE]:
            wp_accuracy = self.get_parameter("WPNAV_RADIUS", retry=2)
            wp_accuracy = wp_accuracy * 0.01  # cm to m
        if self.mav.mav_type in [mavutil.mavlink.MAV_TYPE_FIXED_WING,
                                 mavutil.mavlink.MAV_TYPE_GROUND_ROVER,
                                 mavutil.mavlink.MAV_TYPE_SURFACE_BOAT]:
            wp_accuracy = self.get_parameter("WP_RADIUS", retry=2)
        if wp_accuracy is None:
            raise ValueError()

        def send_speed_vector(vx, vy, vz, mav_frame):
            self.mav.mav.set_position_target_global_int_send(
                0,  # timestamp
                1,  # target system_id
                1,  # target component id
                mav_frame,
                MAVLINK_SET_POS_TYPE_MASK_POS_IGNORE |
                MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                MAVLINK_SET_POS_TYPE_MASK_FORCE |
                MAVLINK_SET_POS_TYPE_MASK_YAW_IGNORE |
                MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                0,
                0,
                0,
                vx,  # vx
                vy,  # vy
                vz,  # vz
                0,  # afx
                0,  # afy
                0,  # afz
                0,  # yaw
                0,  # yawrate
            )

        for frame_name, frame in MAV_FRAMES.items():
            self.start_test("Testing Set Velocity in %s" % frame_name)
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            target_vy = 1.0
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            if test_vz:
                target_vz = 1.0
            else:
                target_vz = 0.0
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            if test_vz:
                target_vz = -1.0
            else:
                target_vz = 0.0
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            target_vx = -1.0
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            target_vy = -1.0
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            target_vx = 0.0
            target_vy = 0.0
            target_vz = 0.0
            if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                          the_function=lambda: send_speed_vector(target_vx, target_vy, target_vz, frame)):
                raise NotAchievedException()

            if test_heading:
                self.start_test("Testing Yaw targetting in %s" % frame_name)

                def send_yaw_target(yaw, mav_frame):
                    self.mav.mav.set_position_target_global_int_send(
                        0,  # timestamp
                        1,  # target system_id
                        1,  # target component id
                        mav_frame,
                        MAVLINK_SET_POS_TYPE_MASK_POS_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_FORCE |
                        MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                        0,
                        0,
                        0,
                        0,  # vx
                        0,  # vy
                        0,  # vz
                        0,  # afx
                        0,  # afy
                        0,  # afz
                        yaw,  # yaw
                        0,  # yawrate
                    )

                target_vx = 1.0
                target_vy = 1.0
                if test_vz:
                    target_vz = -1.0
                else:
                    target_vz = 0.0

                def send_yaw_target_vel(yaw, vx, vy, vz, mav_frame):
                    self.mav.mav.set_position_target_global_int_send(
                        0,  # timestamp
                        1,  # target system_id
                        1,  # target component id
                        mav_frame,
                        MAVLINK_SET_POS_TYPE_MASK_POS_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_FORCE |
                        MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                        0,
                        0,
                        0,
                        vx,  # vx
                        vy,  # vy
                        vz,  # vz
                        0,  # afx
                        0,  # afy
                        0,  # afz
                        yaw,  # yaw
                        0,  # yawrate
                    )

                target_yaw = 42.0
                if not self.wait_heading(target_yaw, maintain_target_time=5, timeout=timeout,
                                         the_function=lambda: send_yaw_target(math.radians(target_yaw), frame)):
                    raise NotAchievedException()

                target_yaw = 0.0
                if not self.wait_heading(target_yaw, maintain_target_time=5, timeout=timeout,
                                         the_function=lambda: send_yaw_target(target_yaw, frame)):
                    raise NotAchievedException()

                target_yaw = 42.0
                if not self.wait_heading(target_yaw, maintain_target_time=5, timeout=timeout,
                                         the_function=lambda: send_yaw_target_vel(math.radians(target_yaw),
                                                                                  target_vx, target_vy,
                                                                                  target_vz, frame)):
                    raise NotAchievedException()
                if not self.wait_speed_vector(target_vx, target_vy, target_vz,
                                              the_function=lambda: send_yaw_target_vel(math.radians(target_yaw),
                                                                                       target_vx, target_vy,
                                                                                       target_vz, frame)):
                    raise NotAchievedException()

                target_yaw = 0.0
                target_vx = 0.0
                target_vy = 0.0
                target_vz = 0.0
                if not self.wait_heading(target_yaw, maintain_target_time=5, timeout=timeout,
                                         the_function=lambda: send_yaw_target_vel(math.radians(target_yaw),
                                                                                  target_vx, target_vy,
                                                                                  target_vz, frame)):
                    raise NotAchievedException()
                if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                              the_function=lambda: send_yaw_target_vel(math.radians(target_yaw),
                                                                                       target_vx, target_vy,
                                                                                       target_vz, frame)):
                    raise NotAchievedException()

            if test_yaw_rate:
                self.start_test("Testing Yaw Rate targetting in %s" % frame_name)

                def send_yaw_rate(rate, mav_frame):
                    self.mav.mav.set_position_target_global_int_send(
                        0,  # timestamp
                        1,  # target system_id
                        1,  # target component id
                        mav_frame,
                        MAVLINK_SET_POS_TYPE_MASK_POS_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_FORCE |
                        MAVLINK_SET_POS_TYPE_MASK_YAW_IGNORE,
                        0,
                        0,
                        0,
                        0,  # vx
                        0,  # vy
                        0,  # vz
                        0,  # afx
                        0,  # afy
                        0,  # afz
                        0,  # yaw
                        rate,  # yawrate
                    )

                target_vx = 1.0
                target_vy = 1.0
                if test_vz:
                    target_vz = -1.0
                else:
                    target_vz = 0.0

                def send_yaw_rate_vel(rate, vx, vy, vz, mav_frame):
                    self.mav.mav.set_position_target_global_int_send(
                        0,  # timestamp
                        1,  # target system_id
                        1,  # target component id
                        mav_frame,
                        MAVLINK_SET_POS_TYPE_MASK_POS_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                        MAVLINK_SET_POS_TYPE_MASK_FORCE |
                        MAVLINK_SET_POS_TYPE_MASK_YAW_IGNORE,
                        0,
                        0,
                        0,
                        vx,  # vx
                        vy,  # vy
                        vz,  # vz
                        0,  # afx
                        0,  # afy
                        0,  # afz
                        0,  # yaw
                        rate,  # yawrate
                    )

                target_rate = 1.0
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate(math.radians(target_rate), frame)):
                    raise NotAchievedException()

                target_rate = -1.0
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate(math.radians(target_rate), frame)):
                    raise NotAchievedException()
                target_rate = 0.0
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate(math.radians(target_rate), frame)):
                    raise NotAchievedException()

                target_rate = 1.0
                if not self.wait_yaw_speed(target_rate,
                                           the_function=lambda: send_yaw_rate_vel(math.radians(target_rate),
                                                                                  target_vx, target_vy,
                                                                                  target_vz, frame)):
                    raise NotAchievedException()
                if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                              the_function=lambda: send_yaw_rate_vel(math.radians(target_rate),
                                                                                     target_vx, target_vy,
                                                                                     target_vz, frame)):
                    raise NotAchievedException()

                target_rate = -1.0
                target_vx = -1.0
                target_vy = -1.0
                if test_vz:
                    target_vz = 1.0
                else:
                    target_vz = 0.0
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate_vel(math.radians(target_rate),
                                                                                  target_vx, target_vy,
                                                                                  target_vz, frame)):
                    raise NotAchievedException()
                if not self.wait_speed_vector(target_vx, target_vy, target_vz, timeout=timeout,
                                              the_function=lambda: send_yaw_rate_vel(math.radians(target_rate),
                                                                                     target_vx, target_vy,
                                                                                     target_vz, frame)):
                    raise NotAchievedException()

                target_rate = 0.0
                target_vx = 0.0
                target_vy = 0.0
                target_vz = 0.0
                if not self.wait_yaw_speed(target_rate, timeout=timeout,
                                           the_function=lambda: send_yaw_rate_vel(math.radians(target_rate),
                                                                                  target_vx, target_vy,
                                                                                  target_vz, frame)):
                    raise NotAchievedException()
                if not self.wait_speed_vector(target_vx, target_vx, target_vx, timeout=timeout,
                                              the_function=lambda: send_yaw_rate_vel(math.radians(target_rate),
                                                                                     target_vx, target_vy,
                                                                                     target_vz, frame)):
                    raise NotAchievedException()

            current_loc = self.mav.location()
            if test_vz and current_loc.alt < 30:
                self.progress("Altitude too low, going to safe altitude")
                self.mav.mav.set_position_target_global_int_send(
                    0,  # timestamp
                    1,  # target system_id
                    1,  # target component id
                    mavutil.mavlink.MAV_FRAME_GLOBAL,
                    MAVLINK_SET_POS_TYPE_MASK_VEL_IGNORE |
                    MAVLINK_SET_POS_TYPE_MASK_ACC_IGNORE |
                    MAVLINK_SET_POS_TYPE_MASK_FORCE |
                    MAVLINK_SET_POS_TYPE_MASK_YAW_RATE_IGNORE,
                    current_loc.lat * 1.0e7,  # lat
                    current_loc.lng * 1.0e7,  # lon
                    40,  # alt
                    0,  # vx
                    0,  # vy
                    0,  # vz
                    0,  # afx
                    0,  # afy
                    0,  # afz
                    0,  # yaw
                    0,  # yawrate
                )
                if not self.wait_location(current_loc, accuracy=wp_accuracy, timeout=timeout, target_altitude=current_loc.alt,
                                          height_accuracy=2):
                    raise NotAchievedException()

    @abc.abstractmethod
    def autotest(self):
        """Autotest used by ArduPilot autotest CI."""
        pass
