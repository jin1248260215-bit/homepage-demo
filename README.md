# Windysunny 的个人主页

金正煊（Windysunny）的个人网站，使用 HTML、CSS 和原生 JavaScript 制作，部署在 Vercel。

**网页地址：https://windysunny-space.vercel.app/**

## 页面

- 首页：四个子页面的简洁入口。
- 个人简介：姓名、昵称与个人空间介绍。
- 金融市场：10 个国内外金融市场板块、官方资料入口及带日期的公告。内容为资料汇编，不是实时行情。
- 个人日历：添加、编辑、删除重要日期，填写时间、分类和备注。
- 作业仓库：按日期展示公开作业，可按课程筛选；暂未发布作业时展示空清单。

## 访问与预览

线上直接访问网页地址即可。代码是静态网站，无需安装项目依赖或执行构建。

本地预览需通过静态 HTTP 服务打开项目根目录，而非双击 HTML 文件，以确保以 `/` 开头的资源路径及作业清单请求能正常工作。

## 项目结构

```text
index.html              首页
about/index.html        个人简介
markets/index.html      金融市场
calendar/index.html     个人日历
assignments/index.html  作业仓库
assignments/data.json   公开作业清单
app.js                  公共导航与日历数据读取
calendar.js             日历交互
assignments.js          作业清单展示
style.css               页面样式与移动适配
vercel.json             静态部署配置
```

## 发布作业

在 `assignments/data.json` 中添加作业条目后重新部署，所有访客便能看到同一份公开清单。每条需包含 `title`（标题）、`course`（课程）、`date`（YYYY-MM-DD）和 `url`（可访问的作业网址）；可选 `description`（说明）及 `type`（文档、代码、报告等）。

作业仓库固定地址：https://windysunny-space.vercel.app/assignments/

## 数据说明

日历记录仅保存在当前浏览器的 localStorage，不上传服务器，也不会提交到此代码仓库。它不跨设备同步，清除网站数据后记录会丢失。

`.env*`、`.vercel/`、登录凭据及本地缓存不包含在仓库中。
