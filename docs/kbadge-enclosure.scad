// K-Badge 外壳 · 参数化模型
// ---------------------------------------------------------------
// 用法：
//   1. 装 OpenSCAD（免费，openscad.org），打开本文件
//   2. 改下面「参数」区里的数字（换成你实测 / 卖家图纸上的尺寸）
//   3. 改 part = "panel" / "back" / "base" / "lid"
//   4. 面板和背板：F6 渲染后 File → Export → Export as DXF（拿去激光切割）
//      底座和盖板：F6 渲染后 File → Export → Export as STL（拿去 3D 打印）
//
// 注意：所有尺寸单位是毫米（mm）。参数默认值只是占位，必须按实物改。
// ---------------------------------------------------------------

// ============ 参数 ============

// 屏幕模块的 PCB 外形（不含排针伸出的部分）
board_w = 52.0;
board_h = 72.0;

// 屏幕可视区（能显示字的那块玻璃）
win_w = 43.2;
win_h = 57.6;

// 可视区中心相对 PCB 中心的偏移（屏幕不在正中时用，一般填 0）
win_off_x = 0.0;
win_off_y = 0.0;

// 外壳
wall   = 2.0;   // 板厚 / 壁厚
margin = 4.0;   // PCB 边缘到外壳边缘的余量
post_h = 12.0;  // 内部净高（铜柱高度）

// 螺丝
screw_inset = 4.0;  // 螺丝孔中心到外壳边缘
screw_d     = 2.2;  // M2 过孔直径

// 侧边 USB 开孔（相对背板左下角的位置与大小），不合适就先把 usb_cut 设 false
usb_cut = true;
usb_x = 18.0;
usb_y = 0.0;    // 从底面算起
usb_w = 12.0;
usb_h = 5.0;

// 要输出哪个零件
part = "panel";   // panel | back | base | lid

// ============ 以下不用改 ============

W = board_w + 2 * margin;
H = board_h + 2 * margin;
$fn = 32;

module hole_grid() {
    for (x = [screw_inset, W - screw_inset])
        for (y = [screw_inset, H - screw_inset])
            translate([x, y]) circle(d = screw_d);
}

module win() {
    translate([(W - win_w) / 2 + win_off_x, (H - win_h) / 2 + win_off_y])
        square([win_w, win_h]);
}

// 面板：2D，激光切割用
module panel_2d() {
    difference() {
        square([W, H]);
        win();
        hole_grid();
    }
}

// 背板：2D，激光切割用
module back_2d() {
    difference() {
        square([W, H]);
        hole_grid();
    }
}

// 底座：3D，含支撑柱与 USB 开孔
module base_3d() {
    difference() {
        cube([W, H, post_h + wall]);
        translate([wall, wall, wall])
            cube([W - 2 * wall, H - 2 * wall, post_h + wall]);
        if (usb_cut)
            translate([usb_x, usb_y, wall + 2])
                cube([usb_w, wall + 0.2, usb_h]);
    }
    for (x = [screw_inset, W - screw_inset])
        for (y = [screw_inset, H - screw_inset])
            translate([x, y, wall])
                difference() {
                    cylinder(d = 6, h = post_h - 1);
                    translate([0, 0, -0.1])
                        cylinder(d = screw_d, h = post_h + 0.2);
                }
}

// 盖板：3D，带屏幕开窗
module lid_3d() {
    difference() {
        cube([W, H, wall]);
        translate([0, 0, -0.1]) {
            linear_extrude(height = wall + 0.2) win();
            linear_extrude(height = wall + 0.2) hole_grid();
        }
    }
}

// ============ 输出 ============
if (part == "panel")      panel_2d();
else if (part == "back")  back_2d();
else if (part == "base")  base_3d();
else if (part == "lid")   lid_3d();
