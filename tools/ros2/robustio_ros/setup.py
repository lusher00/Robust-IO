from setuptools import setup

package_name = "robustio_ros"

setup(
    name=package_name,
    version="0.3.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/robustio.launch.py"]),
        ("share/" + package_name + "/config", ["config/robustio.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Ryan Lush",
    maintainer_email="ryan.lush@gmail.com",
    description="ROS 2 driver for the Robust IO board",
    entry_points={"console_scripts": ["robustio_node = robustio_ros.node:main"]},
)
