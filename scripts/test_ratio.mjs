import { computeRatio } from "./unit_alignment.mjs";

const testCases = [
  { storeName: '维达 线条小狗联名款 初肌秘密加厚洁净一次性洗脸巾L码60抽/包', storeSpec: '60抽/包', pddSpec: '240片', expected: 4 }, // 240 / 60 = 4
  { storeName: '柔巾卷洗脸巾一次性纯棉洁面巾 家庭装80片', storeSpec: '80片*1包', pddSpec: '240片', expected: 3 }, // 240 / 80 = 3
  { storeName: '柔巾卷洗脸巾一次性纯棉洁面巾 家庭装80片', storeSpec: '80片*1包', pddSpec: '480片', expected: 6 }, // 480 / 80 = 6
  { storeName: '维达 线条小狗联名款 初肌秘密加厚洁净一次性洗脸巾L码60抽/包', storeSpec: '60抽/包', pddSpec: '480片', expected: 8 }, // 480 / 60 = 8
  { storeName: '维达 线条小狗联名款 初肌秘密加厚洁净一次性洗脸巾L码60抽/包', storeSpec: '60抽/包', pddSpec: '【60抽单包】', expected: 1 },
  { storeName: '维达 线条小狗联名款 初肌秘密加厚洁净一次性洗脸巾L码60抽/包', storeSpec: '60抽/包', pddSpec: '【120片/包】1包', expected: 1 },
  { storeName: '艾咪艾咪/多美辰 婴儿专用棉签 200支/盒', storeSpec: '200支/盒', pddSpec: '600支【3盒装】', expected: 3 },
  { storeName: '艾咪艾咪/多美辰 婴儿专用棉签 200支/盒', storeSpec: '200支/盒', pddSpec: '600支', expected: 3 },
  { storeName: '屈臣氏 氨基酸净透卸妆湿巾 25片／包', storeSpec: '25片*1包', pddSpec: '75片【3包】', expected: 3 },
  { storeName: '屈臣氏 氨基酸净透卸妆湿巾 25片／包', storeSpec: '25片*1包', pddSpec: '75片', expected: 3 },
  { storeName: '菜板防霉双面家用切菜板 20*31cm/个', storeSpec: '20*31cm/个', pddSpec: '20*30厘米（100只塑料自粘袋）', expected: 1 },
  { storeName: '双鹿电池5号 2节/卡', storeSpec: '2节/卡', pddSpec: '20节', expected: 10 },
  { storeName: '红牛维生素功能饮料250ml', storeSpec: '250ml*1罐', pddSpec: '250ml*24罐整箱', expected: 24 }
];

console.log("=== 正在运行包装换算比率回归测试 (13 个核心测试用例) ===");
let allPassed = true;
let idx = 1;
for (const tc of testCases) {
  const actual = computeRatio(tc.storeName, tc.storeSpec, tc.pddSpec, '');
  const pass = actual === tc.expected;
  console.log(`[Case ${idx.toString().padStart(2, '0')}] ${pass ? 'PASS' : 'FAIL'} | 门店: ${tc.storeSpec} | 供货商: ${tc.pddSpec} -> 期望比率: ${tc.expected}, 实际计算: ${actual}`);
  if (!pass) allPassed = false;
  idx++;
}

if (allPassed) {
  console.log(">>> 回归测试全部通过 (13/13 PASS) <<<");
} else {
  console.error(">>> 存在测试未通过，请检查单位解析逻辑! <<<");
  process.exit(1);
}
