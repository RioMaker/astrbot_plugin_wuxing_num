# 五行数字卦山水底图

`ink_mountains_v1.png` 为内置 imagegen 生成的独立无字背景素材，随插件保存；运行时不调用图片生成服务，不依赖临时目录或外网。

- 参考：本任务已获用户认可的东方幻想风概念图，仅参考山水、色调与氛围。
- 内容：深墨色留白、两侧层叠山体与薄雾、下部湖面倒影；无数字、文字、五行徽记、箭头或成败判定。
- 生成方式：内置 `image_gen`，非 CLI/API 回退。
- 所有数字、标题、徽记、象意、光晕和流转关系均由本地渲染器另外绘制。原图只作无字背景，不携带任何卦象数据。
- 原文件按生成结果保存，不修改源图片；渲染时按输出尺寸居中适配，并对底部断语区施加渐变暗色遮罩。
- 缺失或无法读取时，回退到程序绘制的深色山形背景，不影响数字卦计算和出图。

## 最终生成提示词

```text
Use case: background-extraction / production UI background asset. Use the supplied concept as a visual mood reference ONLY. Generate a clean EMPTY atmospheric background plate for this Chinese five-element divination interface. Remove ALL typography, ALL Chinese and English letters, ALL numbers, ALL elemental emblems, ALL orbits/circles/arrows, ALL UI frames, borders, gold ornaments, dots and indicators. Absolutely no text or interface shapes of any kind. Preserve and elevate ONLY the cinematic ink-navy landscape atmosphere behind the interface. Portrait 3:4 composition. Upper 60 percent: very dark obsidian blue-black softly textured negative space, faint volumetric cool haze, subtle vignette, a quiet dark center reserved for high-contrast programmatically drawn text and diagrams. Lower region: exquisitely detailed layered Chinese karst mountains emerge only along LEFT and RIGHT margins from 56 to 74 percent image height; realistic craggy silhouettes, mist between ridgelines, restrained cyan rim illumination, rich painterly-photographic texture, NOT flat vector mountains. At roughly 75 percent height a calm dark lake horizon connects the sides, subtle champagne and moon-blue glints reflected as delicate horizontal water ripples. Leave the middle valley spacious and dark. Bottom 20 percent fades gradually into near-black with just faint water texture, reserved for a verdict paragraph. Keep high-frequency landscape detail out of top half and central 45 percent width. Premium oriental fantasy, enigmatic, refined, dark and luxurious. No actual sun or moon disk, no castles, no people, no buildings, no symbols. It is a reusable BACKGROUND ONLY, not a new complete UI mockup. Colors deep #071016, #0d1c27, #172c39; no bright blue sky, no bright white fog.
```
