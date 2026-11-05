// 虚拟屏服务接口（跑在 Shizuku UserService 里，shell 身份）
package com.xiaoban.app;

interface IXiaobanDisplay {
    /** 创建虚拟屏，返回 displayId；失败返回 -1。 */
    int createDisplay(int width, int height, int dpi);

    /** 释放虚拟屏。 */
    void releaseDisplay();

    /** 当前虚拟屏 id，没有返回 -1。 */
    int displayId();

    /** 在虚拟屏上启动应用。 */
    boolean launchApp(String pkg, int displayId);

    /** 点一下。 */
    boolean tap(int displayId, int x, int y);

    /** 滑动。 */
    boolean swipe(int displayId, int x1, int y1, int x2, int y2, int durationMs);

    /** 按键（KEYCODE_*）。 */
    boolean key(int displayId, int keyCode);

    /** 输入文字。 */
    boolean text(int displayId, String value);

    /** 截一张虚拟屏的图（PNG 字节）。 */
    byte[] screenshot(int displayId);

    /** 状态描述（JSON 字符串）。 */
    String info();
}
