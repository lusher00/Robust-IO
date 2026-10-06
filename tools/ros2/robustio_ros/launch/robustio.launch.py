import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    params = os.path.join(get_package_share_directory("robustio_ros"), "config", "robustio.yaml")
    return LaunchDescription([
        Node(package="robustio_ros", executable="robustio_node", name="robustio",
             parameters=[params], output="screen"),
    ])
