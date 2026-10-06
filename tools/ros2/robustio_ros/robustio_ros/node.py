"""ROS 2 driver for the Robust IO board.

Publishes (relative to the node name, default /robustio):
  ~/inputs            std_msgs/UInt32             bit n = input n closed (0..13 SG0..SG13, 14..21 SP0..SP7);
                                                  on change and at publish_rate
  ~/output_states     std_msgs/UInt8MultiArray    [commanded, on, tripped, device_fault, off_high] masks
  ~/output_currents   std_msgs/Float32MultiArray  8 values, A
  ~/motor_duty        std_msgs/Int8MultiArray     actual duty, percent
  ~/motor_currents    std_msgs/Float32MultiArray  2 values, A
  /diagnostics        diagnostic_msgs/DiagnosticArray, 1 Hz

Subscribes:
  ~/outputs_cmd       std_msgs/UInt8MultiArray    [mask, values]: outputs in mask set to the bit in values
  ~/motor_cmd         std_msgs/Int8MultiArray     [duty0, duty1], percent -100..100

Services:
  ~/stop              std_srvs/Trigger            outputs off, motors 0
  ~/clear_faults      std_srvs/Trigger            clear latched output trips and the motor fault

Safety: the board switches everything off when its host goes quiet. This node
only keeps the board alive while it keeps receiving commands: if no message on
~/outputs_cmd or ~/motor_cmd arrives for cmd_timeout seconds, the keepalive
stops and the board times out. A controller that wants outputs held on must
keep publishing.
"""
import time

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray, Int8MultiArray, UInt8MultiArray, UInt32
from std_srvs.srv import Trigger

from robustio import RobustIO, RobustIOError, open_bus
from robustio import protocol as p


class RobustIONode(Node):
    def __init__(self):
        super().__init__("robustio")
        self.declare_parameter("interface", "socketcan")
        self.declare_parameter("channel", "can0")
        self.declare_parameter("bitrate", 250000)
        self.declare_parameter("node_id", 0)
        self.declare_parameter("publish_rate", 10.0)
        self.declare_parameter("cmd_timeout", 0.5)
        g = lambda n: self.get_parameter(n).value

        self.cmd_timeout = float(g("cmd_timeout"))
        self.last_cmd = 0.0
        self.bus = open_bus(g("interface"), g("channel"), int(g("bitrate")))
        self.io = RobustIO(self.bus, int(g("node_id")), keepalive_gate=self._commanded_recently)
        self.get_logger().info(f"Robust IO node {g('node_id')} on {g('interface')} {g('channel')}")

        self.pub_inputs = self.create_publisher(UInt32, "~/inputs", 10)
        self.pub_out = self.create_publisher(UInt8MultiArray, "~/output_states", 10)
        self.pub_cur = self.create_publisher(Float32MultiArray, "~/output_currents", 10)
        self.pub_mduty = self.create_publisher(Int8MultiArray, "~/motor_duty", 10)
        self.pub_mcur = self.create_publisher(Float32MultiArray, "~/motor_currents", 10)
        self.pub_diag = self.create_publisher(DiagnosticArray, "/diagnostics", 10)

        self.create_subscription(UInt8MultiArray, "~/outputs_cmd", self._on_outputs_cmd, 10)
        self.create_subscription(Int8MultiArray, "~/motor_cmd", self._on_motor_cmd, 10)
        self.create_service(Trigger, "~/stop", self._srv_stop)
        self.create_service(Trigger, "~/clear_faults", self._srv_clear)

        self._last_inputs = None
        self.create_timer(1.0 / float(g("publish_rate")), self._publish)
        self.create_timer(0.02, self._publish_inputs_on_change)
        self.create_timer(1.0, self._publish_diagnostics)

    def _commanded_recently(self) -> bool:
        return time.monotonic() - self.last_cmd < self.cmd_timeout

    # ------------------------------------------------------------ commands

    def _on_outputs_cmd(self, msg: UInt8MultiArray) -> None:
        if len(msg.data) < 2:
            self.get_logger().warn("outputs_cmd needs [mask, values]")
            return
        self.last_cmd = time.monotonic()
        self.io.set_outputs(int(msg.data[0]), int(msg.data[1]))

    def _on_motor_cmd(self, msg: Int8MultiArray) -> None:
        if len(msg.data) < 2:
            self.get_logger().warn("motor_cmd needs [duty0, duty1]")
            return
        d0, d1 = (max(-100, min(100, int(v))) for v in msg.data[:2])
        self.last_cmd = time.monotonic()
        self.io.set_motors(d0, d1)

    def _srv_stop(self, req, resp):
        self.io.stop()
        resp.success, resp.message = True, "outputs off, motors 0"
        return resp

    def _srv_clear(self, req, resp):
        self.io.clear_faults()
        resp.success, resp.message = True, "faults cleared"
        return resp

    # ------------------------------------------------------------ status

    def _publish_inputs_on_change(self) -> None:
        bits = self.io.inputs.bits
        if bits != self._last_inputs and self.io.online():
            self._last_inputs = bits
            self.pub_inputs.publish(UInt32(data=bits))

    def _publish(self) -> None:
        if not self.io.online():
            return
        io = self.io
        self.pub_inputs.publish(UInt32(data=io.inputs.bits))
        o = io.outputs
        self.pub_out.publish(UInt8MultiArray(data=[o.commanded, o.on, o.tripped, o.device_fault, o.off_high]))
        self.pub_cur.publish(Float32MultiArray(data=[float(a) for a in io.currents.amps]))
        self.pub_mduty.publish(Int8MultiArray(data=[int(d) for d in io.motors.duty]))
        self.pub_mcur.publish(Float32MultiArray(data=[float(a) for a in io.motors.amps]))

    def _publish_diagnostics(self) -> None:
        io, hb = self.io, self.io.heartbeat
        st = DiagnosticStatus(name=f"robustio: node {io.node}", hardware_id=f"robustio-{io.node}")
        if not io.online() or hb is None:
            st.level, st.message = DiagnosticStatus.ERROR, "no heartbeat"
        else:
            problems = []
            if not hb.inputs_valid:
                problems.append("inputs not valid")
            if hb.motor_fault:
                problems.append("motor fault latched")
            if hb.output_latched:
                problems.append("output latched off")
            if hb.host_timed_out:
                problems.append("host timed out")
            st.level = DiagnosticStatus.WARN if problems else DiagnosticStatus.OK
            st.message = ", ".join(problems) or "ok"
            st.values = [KeyValue(key=k, value=str(v)) for k, v in (
                ("firmware", f"{hb.version[0]}.{hb.version[1]}"), ("reset cause", hb.reset_text()),
                ("host active", hb.host_active), ("CAN TEC", hb.tec), ("CAN REC", hb.rec),
                ("frames dropped", hb.tx_dropped), ("config from defaults", hb.config_defaults),
                ("motor fault count", io.motors.fault_count))]
        arr = DiagnosticArray(status=[st])
        arr.header.stamp = self.get_clock().now().to_msg()
        self.pub_diag.publish(arr)

    def destroy_node(self):
        try:
            self.io.stop()
            time.sleep(0.05)
        except Exception:
            pass
        self.io.close()
        self.bus.shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RobustIONode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
