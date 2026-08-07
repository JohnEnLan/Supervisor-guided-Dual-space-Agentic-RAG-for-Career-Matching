import { describe, expect, it } from "vitest";

import { apiFixtures } from "./apiFixtures";

describe("conversation fixture projector parity", () => {
  it("uses the production projector copy and result counts", () => {
    const conversation = apiFixtures.runConversation("completed", null, 2);

    expect(conversation.messages.map((message) => message.text)).toEqual([
      "欢迎来到职业规划服务群。我是项目经理 PM，本次由需求顾问小意、岗位顾问小检和规划师小策协作，依次完成需求确认、岗位检索、策略规划与发布核查。我们会如实说明匹配依据与限制，建议不代表 offer 承诺。",
      "本次 Match Brief 已确认：目标是“Find backend engineer roles matching my Python experience”。本次检索约束为 {\"locations\":[\"Shanghai\"],\"need_visa_sponsor\":false}，已记录并传入检索计划；软偏好为 {\"preferred_industries\":[\"tech\"]}，用于排序加权；暂不考虑的岗位为 [\"sales\"]；计划返回最多 5 个结果。",
      "我确认小检接收的约束与确认单一致，现交给小检执行。",
      "我已接手确认单，岗位检索正在执行：适用的 metadata 条件筛选 → BM25/Dense 并行 → job_id 级 RRF 融合。你要求的 Shanghai 我已锁定为硬条件，绝不放宽。",
      "检索与融合已完成，候选集已提交 PM 进行交接检查。",
      "小检返回了 2 个候选；我核对了候选集、排序与证据完整性，现交给小策。",
      "我正在基于候选岗位开展能力缺口分析，并生成有证据约束的简历建议与职业路径；所有建议只引用简历原始证据和用户确认的澄清证据，不补写未经证实的经历。",
      "缺口分析与简历建议已生成，现提交 PM 做最终发布核查。如果你之后想让我基于某个岗位细化简历，可在结果卡提交反馈或开启新咨询。",
      "进入最终核查检查点：检查硬约束、JD/简历证据可追溯性、建议可执行性与结果完整性。必要时只允许一次受控重检索或修复。",
      "本次规划已完成：Now Fit 1 个、Stretch Fit 1 个、Bridge Role 0 个；warning 0 项。请前往 Results 页查看岗位证据、缺口分析、简历建议与职业路径详情。匹配结果仅供求职决策参考，不构成 offer 承诺。",
    ]);
  });
});
