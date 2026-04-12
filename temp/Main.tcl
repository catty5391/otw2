#SAP2000转Opensees
#主程序
#Sap2000模型文件名：Z33101B-54
#Sap2000模型路径名：D:\常用文件夹\技能学习\opensees\自重荷载施加测试\Z33101B-54模型
#时间：2025年12月5日 18:44:37

#历史消息清除
wipe;

#设置结果文件夹路径
if {[file exists output] == 0} {
    file mkdir output;
}

#设置大变形
set transfType1 Corotational
#Corotational
#Linear

#设置模型自由度（3维）
model BasicBuilder -ndm 3 -ndf 6

#导入节点位置信息
source Node.tcl

#导入节点质量信息
source Mass.tcl

#导入约束信息
source Fix.tcl

#导入材料信息
source Material.tcl

#导入截面信息
source Section.tcl

#导入坐标转换信息
source Geomtransf.tcl

#导入单元信息
source Element.tcl

#设置时间序列
timeSeries Linear 1

#导入自重信息
source GNLoad.tcl

#导入分析信息
#模态分析
source Analysis1.tcl

#导入分析信息
#自重分析
source Analysis2.tcl


#导入输出信息
source Recorder.tcl

loadConst -time 0.0
#设置瑞利阻尼
rayleigh 0.4045 1.324e-3 0 0

#导入地震动信息
timeSeries Path 2 -dt 0.01 -filePath THFile/GM_261.txt

#施加地震动
pattern UniformExcitation 2 2 -accel 2

#分析设置
system SparseSYM

numberer Plain

integrator Newmark 0.5 0.25

test NormDispIncr 1.0e-5 80 2

analysis Transient

analyze 10000 0.005