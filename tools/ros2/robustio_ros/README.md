# robustio_ros

ROS 2 driver for the Robust IO board. It uses the `robustio` Python package in
`tools/python`, so that has to be installed in the same Python environment:

    pip install -e tools/python        # add --break-system-packages on Ubuntu 24.04

Build and run (from a colcon workspace that contains or links this folder):

    colcon build --packages-select robustio_ros
    source install/setup.bash
    ros2 launch robustio_ros robustio.launch.py

Settings are in `config/robustio.yaml`: CAN interface and channel, board node
number, publish rate and command timeout.

## Topics and services

| Name | Type | |
|---|---|---|
| `/robustio/inputs` | std_msgs/UInt32 | bit n = input n closed (0..13 SG0..SG13, 14..21 SP0..SP7) |
| `/robustio/output_states` | std_msgs/UInt8MultiArray | masks: commanded, on, tripped, device fault, off but high |
| `/robustio/output_currents` | std_msgs/Float32MultiArray | 8 values, A |
| `/robustio/motor_duty` | std_msgs/Int8MultiArray | actual duty, % |
| `/robustio/motor_currents` | std_msgs/Float32MultiArray | 2 values, A |
| `/diagnostics` | diagnostic_msgs/DiagnosticArray | 1 Hz, OK / WARN / ERROR with details |
| `/robustio/outputs_cmd` | std_msgs/UInt8MultiArray, subscribed | `[mask, values]` |
| `/robustio/motor_cmd` | std_msgs/Int8MultiArray, subscribed | `[duty0, duty1]`, -100..100 % |
| `/robustio/stop` | std_srvs/Trigger | outputs off, motors 0 |
| `/robustio/clear_faults` | std_srvs/Trigger | clear latched trips and the motor fault |

Examples:

    ros2 topic pub -r 10 /robustio/outputs_cmd std_msgs/UInt8MultiArray "{data: [8, 8]}"     # output 3 on
    ros2 topic pub -r 10 /robustio/motor_cmd std_msgs/Int8MultiArray "{data: [40, 0]}"
    ros2 service call /robustio/stop std_srvs/srv/Trigger

## Safety

The node keeps the board's host timeout satisfied only while commands keep
arriving: if nothing is published on `outputs_cmd` or `motor_cmd` for
`cmd_timeout` seconds (0.5 by default), it stops the keepalive and the board
switches everything off. Publish commands at a steady rate (the `-r 10` above),
not once. If the controlling node crashes, the board turns off.

## Without hardware

Run the firmware simulator (`bash firmware/test/run_sim.sh live`) and set
`interface: sim` and `channel: 127.0.0.1:29536` in the parameters.
