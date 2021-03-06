import rospy
from pid import PID
from lowpass import LowPassFilter

GAS_DENSITY = 2.858
ONE_MPH = 0.44704
DEFAULT_STEER_RATIO = 14.8
DEFAULT_GEAR_RATIO = 2.4 / 1  ## 1st gear ratio 2.4:1
THROTTLE_ADJUSTMENT = 1000.  # magic constant for throttle
BRAKE_ADJUSTMENT = 60  # magic constat for brake
DEFAULT_WEIGHT = 1080.
DEFAULT_WHEEL_RADIUS = 0.335

class Controller(object):
    """
    Drive-by-Wire Twist controller
    """
    def __init__(self, vehicle_mass=1736.35, fuel_capacity=13.5, brake_deadband=.1, decel_limit=-5, accel_limit=1.,
                 wheel_radius=0.2413, wheel_base=2.8498, steer_ratio=14.8, max_lat_accel=3., max_steer_angle=8.):
        """
        Twist controller initialization
        """
        # limits
        self.vehicle_mass = vehicle_mass
        self.fuel_capacity = fuel_capacity
        self.brake_deadband = brake_deadband
        self.decel_limit = decel_limit
        self.accel_limit = accel_limit
        self.wheel_radius = wheel_radius
        self.wheel_base = wheel_base
        self.steer_ratio = steer_ratio
        self.max_lat_accel = max_lat_accel
        self.max_steer_angle = max_steer_angle

        # max torque corresponding to 1.0 throttle
        self.max_acceleration = 1.5
        self.max_acc_torque = self.vehicle_mass * self.max_acceleration * self.wheel_radius
        # max brake torque corresponding to deceleration limit
        self.max_brake_torque = self.vehicle_mass * abs(self.decel_limit) * self.wheel_radius

        # timestamp of the last update
        self.last_update = 0
        self.max_velocity = 50

        self.steer_pid = PID(.4,0,.7, mn=-2.5, mx=2.5)
        self.steer_lowpass = LowPassFilter(1e-4)
        self.throttle_pid = PID(1.,0.,.5, mn=0, mx=1)
        self.throttle_lowpass = LowPassFilter(5e-2)
        self.brake_pid = PID(1.,0.,1.,mn=0,mx=1)
        self.brake_lowpass = LowPassFilter(5e-2)

        # if CTE is too high, this factor will be reduced
        self.speed_factor = 1.

    def reset(self, time, cte):
        """
        reset internal states and timestamp
        """
        self.last_update = time
        self.steer_pid.reset()
        self.steer_lowpass.reset()
        self.brake_pid.reset()
        self.brake_lowpass.reset()
        self.throttle_pid.reset()
        self.throttle_lowpass.reset()

    def control(self, timestamp, target_velocity, current_velocity, cte):
        """
        Control vehicle
        :args: timestamp, target v, current v, cte
        :return: throttle, brake, steering angle
        """
        t_delta = timestamp-self.last_update
        if cte>0:
            cte = max(0., cte-0.1)
        elif cte<0:
            cte = min(0., cte+0.1)

        # adjust speed if CTE is increasing
        if abs(cte) > .75:
            self.speed_factor = max(.4, self.speed_factor*.99)
        elif abs(cte) < .4:
            self.speed_factor = min(1., self.speed_factor/.95)

        throttle, brake, steer = 0., 0., 0.

        # target_velocity *= self.speed_factor  ## @!!!
        # slow down dramatically if vehicle too close to lane line
        # if abs(cte) > 1.2:
        #     target_velocity = min(3., target_velocity)
        """
                if target_velocity > 0:
                    max_acceleration = (target_velocity-current_velocity) / t_delta
                    max_torque = self.vehicle_mass * DEFAULT_GEAR_RATIO * self.wheel_radius * max_acceleration
                    acceleration_normalization = max_torque / (self.accel_limit * DEFAULT_GEAR_RATIO * DEFAULT_WEIGHT * DEFAULT_WHEEL_RADIUS * THROTTLE_ADJUSTMENT)
                    if target_velocity < 20:
                        acceleration_normalization = 1.0
                    print "!!!!an=", acceleration_normalization
                    throttle = self.throttle_pid.step(
                            (target_velocity-current_velocity)/self.max_velocity, t_delta)
                    throttle *= max(5.,current_velocity)*self.max_velocity / acceleration_normalization
                else:
                    throttle = 0

                if (target_velocity == 0 and current_velocity > 0) or (current_velocity * .99 > target_velocity):
                    max_deceleration = (target_velocity-current_velocity) / t_delta
                    max_torque = self.vehicle_mass * self.wheel_radius * max_deceleration
                    deceleration_normalization = max_torque / (self.decel_limit * DEFAULT_WEIGHT * DEFAULT_WHEEL_RADIUS * BRAKE_ADJUSTMENT)
                    if target_velocity < 20:
                        deceleration_normalization = 1.0
                    print "!!!!dn=", deceleration_normalization
                    brake = self.brake_pid.step(
                        (current_velocity-target_velocity)/self.max_velocity, t_delta)
                    brake *= current_velocity*self.max_velocity
                    brake = min(10, brake / deceleration_normalization)
                else:
                    # if no brake is needed then reset, otherwise low pass
                    # filter increases latency
                    self.brake_lowpass.reset()
                    self.brake_lowpass.filt(0., 0.)
                    brake = 0
        """

        delta_t = 1.0 / 2.0

        # convert current velocity from m/s to mph
        current_velocity = current_velocity * 3.6 / 1.6093
        # make lowest speed 2mph for faster approach towards stop line
        if target_velocity > 0.1 and target_velocity < 2.:
            target_velocity = 2
        delta_v = target_velocity - current_velocity

        # approximate and limit acceleration
        acceleration = delta_v / delta_t
        if acceleration > 0:
            acceleration = min(acceleration, self.accel_limit)
        else:
            acceleration = max(acceleration, self.decel_limit)

        if abs(acceleration) > self.brake_deadband:
            # avoid deadband
            # approximate torque, 1:1 gear ratio
            torque = self.wheel_radius * acceleration * self.vehicle_mass

            if torque >= 0:
                throttle = min(torque / self.max_acc_torque, 1.)
            else:
                brake = min(self.max_brake_torque, abs(torque))

        steer = self.steer_pid.step(cte, t_delta) * self.steer_ratio / DEFAULT_STEER_RATIO  # PID normalized to simulator steer ratio

        # rospy.loginfo("thr {:.2f} brake {:.2f} steer {:.2f}".format(throttle, brake, steer))

        self.last_update = timestamp

        # WARNING: low-pass filter on throttle/brake make vehicle move unnaturally at low speeds. Avoid!
        # throttle = self.throttle_lowpass.filt(throttle, t_delta)
        # brake = self.brake_lowpass.filt(brake, t_delta)*100
        # reduce steering magnitude as velocity increases
        steer = self.steer_lowpass.filt(steer/(current_velocity*1.+0.01), t_delta)*10

        return throttle, brake, steer
