/*
   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */
/*
  simple Gripper (Servo) simulation class
*/

#pragma once
#include "stdint.h"
#include <AP_Param/AP_Param.h>

namespace SITL {

class Gripper_Servo {
public:
    Gripper_Servo() {};

    // update Gripper state
    void update(int16_t gripper_pwm, bool on_ground);

    float payload_mass(float alt) const; // kg

    static const struct AP_Param::GroupInfo var_info[];

    AP_Int8  gripper_enable;  // enable gripper sim
    AP_Int8  gripper_servo_pin;

private:

    const uint32_t report_interval = 1000000; // microseconds
    uint64_t last_report_us;

    const float gap = 30; // mm

    float position; // percentage
    float position_slew_rate = 35; // percentage
    float reported_position = -1; // unlikely

    uint64_t last_update_us;

    bool should_report();

    // dangle load from a string:
    const float string_length = 2.0f; // metres
    float load_mass = 0.0f; // kilograms
};

}
