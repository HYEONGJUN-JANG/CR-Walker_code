import json
import numpy as np
import torch
import random
import sys
import os.path as osp
from tqdm import tqdm
from termcolor import colored
from copy import deepcopy
import math
import random

from CR_walker import ProRec
from torch_geometric.data import DataLoader

sys.path.append("..")
from data.redial import ReDial
from data.gorecdial import GoRecDial
from data.metrics import bleu,f1_score,distinct_n_grams
from data.utils import da_tree_serial,utter_lexical_redial,utter_lexical_gorecdial
from sklearn.metrics import precision_score, recall_score
from sklearn.metrics import f1_score as f1_rec_score

def select_intent(sel_intent,mentioned,args):
    device=torch.device('cuda:0')
    attribute_types=set([ 'Person', 'Time', 'Genre', 'Subject'])
    last=[]
    bat=[]  
    sel=[]
    grp=[]
    #itt=[]
    grp_bat=[]
    mask=[]
    node_candidate1=[]
    cur_grp_size=sel_intent.size()[0]
    for i in range(cur_grp_size):
        cand=[]
        last.append(args['none_node'])
        grp_bat.append(i)
        #itt.append(sel_intent[i])
        if sel_intent[i]==0:#chat
            for item in mentioned[i]:
                cand.append(item)
                sel.append(item)
                bat.append(i)
                grp.append(i)
                mask.append(1)
            if len(mentioned[i])==0:
                cand.append(args['none_node'])
                sel.append(args['none_node'])
                bat.append(i)
                grp.append(i)
                mask.append(1)
        elif sel_intent[i]==1:#question
            #print(args['generals'])
            for item in args['generals']:
                cand.append(item)
                sel.append(item)
                bat.append(i)
                grp.append(i)
                mask.append(1)
        else: #recommend
            my_cand=set()
            for item in mentioned[i]:
                if item<args['movie_count']:
                    my_cand=my_cand.union(args['attribute_dict'][item])
                elif args['nodes'][item]['type'] in attribute_types:
                    my_cand.add(item)
            cand=list(my_cand)
            if len(cand)==0:
                cand.append(args['none_node'])
            for item in cand:
                sel.append(item)
                bat.append(i)
                grp.append(i)
                mask.append(1)
        node_candidate1.append(cand)
    sel_index=torch.Tensor(sel).long().to(device=device)
    grp_index=torch.Tensor(grp).long().to(device=device)
    batch_index=torch.Tensor(bat).long().to(device=device)
    score_mask=torch.Tensor(mask).float().to(device=device)
    #print(intent_index)
    grp_bat_index=torch.Tensor(grp_bat).long().to(device=device)
    last_index=torch.Tensor(last).long().to(device=device)
    return sel_index,grp_index,batch_index,grp_bat_index,last_index,node_candidate1,score_mask


def select_layer_1(nodes,step,step_grp,intent_label,node_candidate1,label_1,mentioned,args,rec_cand=None,dataset="redial"):
    device=torch.device('cuda:0')
    cur_grp_size=intent_label.size()[0]
    cand_num=[0 for _ in range(cur_grp_size+1)]
    all_selected=[]
    for i in step_grp:
        cand_num[i]+=1
    start=0
    end=cand_num[0]

    last=[]
    bat=[]  
    sel=[]
    grp=[]
    itt=[]
    grp_bat=[]
    mask=[]

    grp_num=0
    all_candidates=[]

    all_split=[]
    for num in range(cur_grp_size):
        selected=[]
        split_score=[]
        score=step[start:end].tolist()
        if len(node_candidate1[num])!=0:
            best_idx=score.index(max(score))
            if intent_label[num]==0:
                for nod,scr in enumerate(score):
                    if scr>args['threshold'][0][0]:
                        last.append(node_candidate1[num][nod])
                        selected.append(node_candidate1[num][nod])
                        if nodes[node_candidate1[num][nod]]['type']=='Movie':
                            node_candidate2=list(args['attribute_dict'][node_candidate1[num][nod]])+[args['none_node']]
                        else:
                            node_candidate2=[args['none_node']]
                        all_candidates.append(node_candidate2)
                        sel=sel+node_candidate2
                        bat=bat+[num for _ in range(len(node_candidate2))]
                        grp=grp+[grp_num for _ in range(len(node_candidate2))]
                        mask=mask+[1 for _ in range(len(node_candidate2))]
                        grp_bat.append(num)
                        itt.append(intent_label[num])
                        grp_num+=1
            elif intent_label[num]==1:
                step_general_dict=deepcopy(args['generals_dict'])
                #print(step_general_dict)
                for n in mentioned[num]:
                    if nodes[n]['type']!="Attr" and nodes[n]['type']!="None":
                        if nodes[n]['type']=="Person":
                            for rol in nodes[n]['role']:
                                step_general_dict[rol].add(nodes[n]['global'])
                        else:
                            step_general_dict[nodes[n]['type']].add(nodes[n]['global'])
                        if nodes[n]['type']=="Movie":
                            for attr in args['attribute_dict'][nodes[n]['global']]:
                                if nodes[attr]['type']!="Attr":
                                    if nodes[attr]['type']=="Person":
                                        for rol in nodes[attr]['role']:
                                            step_general_dict[rol].add(attr)
                                    else:
                                        step_general_dict[nodes[attr]['type']].add(attr)
                #print(step_general_dict)
                for nod,scr in enumerate(score):
                    if scr>args['threshold'][0][1]:
                        selected.append(node_candidate1[num][nod])
                        last.append(node_candidate1[num][nod])
                        cur_gen=nodes[node_candidate1[num][nod]]['name']
                        node_candidate2=list(step_general_dict[cur_gen])+[args['none_node']]
                        all_candidates.append(node_candidate2)
                        sel=sel+node_candidate2
                        bat=bat+[num for _ in range(len(node_candidate2))]
                        grp=grp+[grp_num for _ in range(len(node_candidate2))]
                        mask=mask+[1 for _ in range(len(node_candidate2)) ]
                        grp_bat.append(num)
                        itt.append(intent_label[num])
                        grp_num+=1
            else:
                if args['sample']>0:
                    score_torch=torch.sigmoid(torch.Tensor(score))
                    top_k=score_torch.topk(min(args['sample'],len(score))).indices.numpy()
                    top_scores=score_torch.topk(min(args['sample'],len(score))).values.numpy()
                    #print(top_scores)
                    split_score.append(top_scores)
                    threshold=1 / (1 + math.exp(-args['threshold'][0][2]))
                    if top_scores[0]>threshold:
                        for nod, top_idx in enumerate(top_k):
                            if top_scores[nod]>threshold:
                                attr_idx=node_candidate1[num][top_idx]
                                selected.append(attr_idx)
                                last.append(attr_idx)
                                if dataset=="redial":
                                    node_candidate2=[mov for mov in range(args['movie_count'])]
                                    my_mask=[0 for mov in range(args['movie_count'])]
                                    # print(attr_idx)
                                    # print(args['attribute_dict'][attr_idx])
                                    for idx in args['attribute_dict'][attr_idx]:
                                        my_mask[idx]=1
                                else:
                                    node_candidate2=rec_cand[num]
                                    my_mask=[1 for mov in range(len(node_candidate2))]

                                all_candidates.append(node_candidate2)
                                sel=sel+node_candidate2
                                bat=bat+[num for _ in range(len(node_candidate2))]
                                grp=grp+[grp_num for _ in range(len(node_candidate2))]
                                mask=mask+my_mask
                                grp_bat.append(num)
                                itt.append(intent_label[num])
                                grp_num+=1
                    else:
                        attr_idx=node_candidate1[num][top_k[0]]
                        selected.append(attr_idx)
                        last.append(attr_idx)
                        if dataset=="redial":
                            node_candidate2=[mov for mov in range(args['movie_count'])]
                            my_mask=[0 for mov in range(args['movie_count'])]
                            # print(attr_idx)
                            # print(args['attribute_dict'][attr_idx])
                            for idx in args['attribute_dict'][attr_idx]:
                                my_mask[idx]=1
                        else:
                            node_candidate2=rec_cand[num]
                            my_mask=[1 for mov in range(len(node_candidate2))]

                        all_candidates.append(node_candidate2)
                        sel=sel+node_candidate2
                        bat=bat+[num for _ in range(len(node_candidate2))]
                        grp=grp+[grp_num for _ in range(len(node_candidate2))]
                        mask=mask+my_mask
                        grp_bat.append(num)
                        itt.append(intent_label[num])
                        grp_num+=1

                else:
                    for nod,scr in enumerate(score):
                        if scr>args['threshold'][0][2]:
                            last.append(node_candidate1[num][nod])
                            selected.append(node_candidate1[num][nod])
                            if dataset=="redial":
                                node_candidate2=[mov for mov in range(args['movie_count'])]
                                my_mask=[0 for mov in range(args['movie_count'])]
                                for idx in args['attribute_dict'][node_candidate1[num][nod]]:
                                    my_mask[idx]=1
                            else:
                                node_candidate2=rec_cand[num]
                                my_mask=[1 for mov in range(len(node_candidate2))]
                            all_candidates.append(node_candidate2)
                            sel=sel+node_candidate2
                            bat=bat+[num for _ in range(len(node_candidate2))]
                            grp=grp+[grp_num for _ in range(len(node_candidate2))]
                            mask=mask+my_mask
                            grp_bat.append(num)
                            itt.append(intent_label[num])
                            grp_num+=1
        all_selected.append(selected)
        all_split.append(split_score)
        
        start+=cand_num[num]
        end+=cand_num[num+1]
    sel_index=torch.Tensor(sel).long().to(device=device)
    grp_index=torch.Tensor(grp).long().to(device=device)
    batch_index=torch.Tensor(bat).long().to(device=device)
    intent_index=torch.Tensor(itt).long().to(device=device)
    grp_bat_index=torch.Tensor(grp_bat).long().to(device=device)
    last_index=torch.Tensor(last).long().to(device=device)
    score_mask=torch.Tensor(mask).float().to(device=device)

    return sel_index,grp_index,batch_index,intent_index,grp_bat_index,last_index,score_mask,all_candidates,all_selected,all_split
            

def select_layer_2(step,step_grp,grp_batch,intent_label,node_candidate2,batch_size,args):
    cur_grp_size=step_grp[-1]+1
    cand_num=[0 for _ in range(cur_grp_size+1)]
    for i in step_grp:
        cand_num[i]+=1
    start=0
    end=cand_num[0]
    selected=[[] for _ in range(batch_size)]
    for num in range(cur_grp_size):
        score=step[start:end].tolist()
        threshold=args['threshold'][1][intent_label[num]]
        k=0
        cur_sel=[]
        for i,scr in enumerate(score):
            if scr>threshold and i!=len(score)-1:
                cur_sel.append(node_candidate2[num][i])
                k+=1
            if k==args['max_leaf']:
                break
        selected[grp_batch[num]].append(cur_sel)
        #index=score.index(max(score))
        #selected[grp_batch[num]].append([node_candidate2[num][index]])
        start+=cand_num[num]
        end+=cand_num[num+1]

    return selected

        
def evaluate_rec_redial(test_loader:DataLoader, model:ProRec,graph_data,args,eval_batch=None):

    recall_1=0
    recall_10=0
    recall_50=0
    intent_accuracy=0
    da_distrib=[0,0,0]
    tot_rec=0
    tot=0
    

    batches=0
    model.eval()

    generated_DAs=[]

    with torch.no_grad():
        for test_batch in tqdm(test_loader):
            tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_indices,sel_batch_indices,sel_group_indices,grp_batch_indices,last_indices,intent_indices,intent_label,label_1,label_2,score_masks,word_index,word_batch_index=model.prepare_data_redial(test_batch.dialog_history,test_batch.mention_history,test_batch.intent,test_batch.node_candidate1,test_batch.node_candidate2,graph_data.edge_type,graph_data.edge_index,test_batch.label_1,test_batch.label_2,test_batch.gold_pos,args['attribute_dict'])

            intent=model.get_intent(tokenized_dialog,all_length,maxlen,init_hidden)
            selected=intent.max(dim=-1).indices
            step1,last_weight1,partial_score_1=model.inference_redial(intent_indices[0],tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_indices[0],sel_batch_indices[0],sel_group_indices[0],grp_batch_indices[0],last_indices[0],score_masks[0],word_index,word_batch_index)
            # rec=model.get_rec(tokenized_dialog,edge_type,edge_index,node_feature,)
            cur_batch_size=intent.size()[0]

            step1=step1.cpu().numpy()
            step_grp=sel_group_indices[0].cpu().numpy()
            # for i in step_grp:
            #     cand_num[i]+=1s
            sel_index_2,grp_index_2,batch_index_2,intent_index_2,grp_bat_index_2,last_index_2,score_mask_2,node_candidate2,selected_1,all_split=select_layer_1(args['nodes'],step1,step_grp,intent_label,test_batch.node_candidate1,test_batch.label_1,test_batch.mention_history,args)
            sel_grp_size=grp_bat_index_2.size()[0]
            step2,_,partial_score_2=model.inference_redial(intent_index_2,tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_index_2,batch_index_2,grp_index_2,grp_bat_index_2,last_index_2,score_mask_2,word_index,word_batch_index,last_weights=last_weight1,layer=1)

            cand_num=[0 for _ in range(sel_grp_size+1)]
            step_grp=grp_index_2.cpu().numpy()
            grp_batch=grp_bat_index_2.cpu().numpy()
            step2=step2.cpu().numpy()
            #partial_score_2=partial_score_2.cpu().numpy()
            intent_label_2=intent_index_2.cpu().numpy()


            for i in step_grp:
                cand_num[i]+=1

            start=0
            end=cand_num[0]
            all_scores=[]
            flags=[0 for _ in range(cur_batch_size)]

            for it in test_batch.intent:
                if it=="recommend":
                    all_scores.append(np.array([0 for _ in range(args['movie_count'])]))
                else:
                    all_scores.append([])

            #print(test_batch.intent)


            for num in range(sel_grp_size):
                my_label=test_batch.label_rec[grp_batch[num]]
                if intent_label_2[num]==2:
                    score=step2[start:end]
                    all_scores[grp_batch[num]]=all_scores[grp_batch[num]]+score#*all_split[grp_batch[num]][0][flags[grp_batch[num]]]
                    flags[grp_batch[num]]+=1
                start+=cand_num[num]
                end+=cand_num[num+1]


            
            for num in range(cur_batch_size):
                my_label=test_batch.label_rec[num]
                wrong_count=[0 for _ in range(len(my_label))]
                if test_batch.intent[num]=="recommend":
                    for item in all_scores[num]:
                        for p,idx in enumerate(my_label):
                            if item>=all_scores[num][idx]:
                                wrong_count[p]+=1
                    for item in wrong_count:
                        tot_rec+=1
                        if item<2:
                            recall_1+=1
                        if item<11:
                            recall_10+=1
                        if item<51:
                            recall_50+=1

            if batches==eval_batch:
                break
            batches+=1
            tot+=cur_batch_size

    recall_1=recall_1/tot_rec
    recall_10=recall_10/tot_rec
    recall_50=recall_50/tot_rec


    print("recall_1",recall_1)
    print('recall_10:',recall_10)
    print("recall_50:",recall_50)

    return recall_1,recall_10,recall_50
    

def evaluate_rec_gorecdial(test_loader:DataLoader, model:ProRec,graph_data, bow_data,args,eval_batch=None):
    pass


def evaluate_gen_redial(test_loader:DataLoader, model:ProRec, graph_data, args, golden_intent=True):
    from train_redial import get_time_kst, save_logs
    model.eval()
    generated_DAs=[]
    generated_utters=[]
    all_gpt_in=[]
    cnt=0
    f1_rec_trues=[]
    f1_rec_preds=[]
    print("With Intent" if args.get('with_intent')=='True' else "***********Without Intent**********")
    from generator import Generator
    gener=Generator(args['gen_conf'])
    with torch.no_grad():
        for test_batch in tqdm(test_loader):
            tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_indices,sel_batch_indices,sel_group_indices,grp_batch_indices,last_indices,intent_indices,intent_label,label_1,label_2,score_masks,word_index,word_batch_index = model.prepare_data_redial(
                test_batch.dialog_history,test_batch.mention_history,test_batch.intent,test_batch.node_candidate1,test_batch.node_candidate2,graph_data.edge_type,graph_data.edge_index,test_batch.label_1,test_batch.label_2,test_batch.gold_pos,args['attribute_dict'])

            # intent : [B,3]
            intent=model.get_intent(tokenized_dialog,all_length,maxlen,init_hidden)
            selected=intent.max(dim=-1).indices # [B]
            cur_batch_size=intent.size()[0] # int: B
            
            
            if golden_intent: # Test_gen 에서 : False
                step1,last_weight1,_=model.inference_redial(intent_indices[0],tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_indices[0],sel_batch_indices[0],sel_group_indices[0],grp_batch_indices[0],last_indices[0],score_masks,word_index,word_batch_index,layer=0)
                step1=step1.cpu().numpy()
                step_grp=sel_group_indices[0].cpu().numpy()
                
                sel_index_2,grp_index_2,batch_index_2,intent_index_2,grp_bat_index_2,last_index_2,score_mask_2,node_candidate2,selected_1,all_split=select_layer_1(args['nodes'],step1,step_grp,intent_label,test_batch.node_candidate1,test_batch.label_1,test_batch.mention_history,args)
                step2,_,_=model.inference_redial(intent_index_2,tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_index_2,batch_index_2,grp_index_2,grp_bat_index_2,last_index_2,score_mask_2,word_index,word_batch_index,last_weights=last_weight1,layer=1)

                selected_2=select_layer_2(step2,grp_index_2.cpu().numpy(),grp_bat_index_2.cpu().numpy(),intent_index_2.cpu().numpy(),node_candidate2,cur_batch_size,args)
                
            else:
                sel_index_1i,grp_index_1i,batch_index_1i,grp_bat_index_1i,last_index_1i,node_candidate1i,score_mask1i=select_intent(selected,test_batch.mention_history,args)
                step1i,last_weight1i,_=model.inference_redial(selected,tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_index_1i,batch_index_1i,grp_index_1i,grp_bat_index_1i,last_index_1i,score_mask1i,word_index,word_batch_index)
                step1i=step1i.cpu().numpy()
                step_grp=grp_index_1i.cpu().numpy()

                sel_index_2,grp_index_2,batch_index_2,intent_index_2,grp_bat_index_2,last_index_2,score_mask_2,node_candidate2,selected_1,all_split = select_layer_1(args['nodes'],step1i,step_grp,selected,node_candidate1i,test_batch.label_1,test_batch.mention_history,args)
                #print("sel_grp_index:",grp_index_2)
                if grp_index_2.size()[0]!=0:
                    step2,_,_ = model.inference_redial(intent_index_2,tokenized_dialog,all_length,maxlen,init_hidden,edge_type,edge_index,mention_index,mention_batch_index,sel_index_2,batch_index_2,grp_index_2,grp_bat_index_2,last_index_2,score_mask_2,word_index,word_batch_index,last_weights=last_weight1i,layer=1)
                    selected_2 = select_layer_2(step2,grp_index_2.cpu().numpy(),grp_bat_index_2.cpu().numpy(),intent_index_2.cpu().numpy(),node_candidate2,cur_batch_size,args)
                else:
                    selected_2=[[[]]]

            
            
            for i in range(len(selected_1)):
                for j in range(len(selected_1[i])):
                    selected_1[i][j]=int(selected_1[i][j])
            for i in range(len(selected_2)):
                for j in range(len(selected_2[i])):
                    for k in range(len(selected_2[i][j])):
                        selected_2[i][j][k]=int(selected_2[i][j][k])
            all_intent=['chat','question','recommend']

            dataset=ReDial(args['data_path'],flag="test")
            hellocnt=0## HJ : TEST HELLO COUNT
            for num in range(cur_batch_size):
                itt=intent_label[num] if golden_intent else selected[num]
                ## HJ: F1_rec Code
                f1_rec_preds.append(1 if all_intent[itt]=='recommend' else 0)
                f1_rec_trues.append(1 if test_batch.intent[num]=='recommend' else 0)
                try:
                    if args.get('with_intent')=='True':
                        # data={'intent':all_intent[itt],'layer1':selected_1[num],'layer2':selected_2[num],'key':test_batch.my_id[num]} # Default
                        data={'intent':all_intent[itt],'layer1':selected_1[num],'layer2':selected_2[num],'key':test_batch.my_id[num]} # HJ With intent
                    else:
                        data={'intent':" ",'layer1':selected_1[num],'layer2':selected_2[num],'key':test_batch.my_id[num]} # HJ Without intent
                except:
                    print(itt,"  ",num)
                    print(all_intent)
                    print(selected_1)
                    print(selected_2)
                    print(test_batch.my_id)
                    continue
                DA=da_tree_serial(data,args['id2name'])
                if len(dataset[cnt].dialog_history)!=0:
                    context=dataset[cnt].dialog_history[-1]
                else: # len 이 0일때 -> 첫발화일때??인지 체크해보기
                    context="hello"
                    hellocnt+=1 ## HJ : TEST HELLO COUNT

                context=utter_lexical_redial(context,args['mid2name'])
                # gpt_in=context+" @ "+DA+" &" ## HJ: Origin
                gpt_in=context+" @ "+DA+" &"
               
                all_gpt_in.append(gpt_in)
                generated, outTok=gener.generate(gpt_in.lower())
                # generated=gener.generate(gpt_in.lower()) # Default
                cur_turn={"generated":generated,"label":utter_lexical_redial(dataset[cnt].oracle_response,args['mid2name'])}
                generated_DAs.append(data)
                generated_utters.append(cur_turn)
                cnt+=1
                ### HJ : CONV_SAVE
                if args.get('save_conv_name'):
                    save_conv(f'../convlog_CRWalker_{args.get("save_conv_name")}.txt',test_batch.dialog_history[num],cur_turn['generated'], cur_turn['label'],gpt_in)
    lines = [item['generated'].strip() for item in generated_utters]
    bleu_array = []
    f1_array = []
    
    k=0
    for item in generated_utters:
        k+=1
        ground, generate = [item['label']], item['generated']
        bleu_array.append(bleu(generate, ground))
        f1_array.append(f1_score(generate, ground))

    Bleu=np.mean(bleu_array)
    f1=np.mean(f1_array)
    dist=[]
    print("\nBLEU:",round(Bleu,3))
    print("\nF1:",round(f1,3))
    print(f'\nPrecision : {round(precision_score(f1_rec_trues, f1_rec_preds),3)}')
    print(f'Recall : {round(recall_score(f1_rec_trues, f1_rec_preds),3)}')
    print(f'F1_Rec_score : {round(f1_rec_score(f1_rec_trues, f1_rec_preds),3)}')
    print(f'Total Test Rec True Counter {len(list(filter(lambda x : x==1, f1_rec_trues)))}')
    print(f'Total Test Rec Pred Counter {len(list(filter(lambda x : x==1, f1_rec_preds)))}')
    save_logs(f"\nOriginal Code BLEU : {round(Bleu,3)}, F1 : {round(f1,3)}", args.get('test_gen_log_path'))
    save_logs(f"Precision : {round(precision_score(f1_rec_trues, f1_rec_preds),3)}", args.get('test_gen_log_path'))
    save_logs(f"Recall : {round(recall_score(f1_rec_trues, f1_rec_preds),3)}", args.get('test_gen_log_path'))
    save_logs(f'F1_Rec_score : {round(f1_rec_score(f1_rec_trues, f1_rec_preds),3)}',args.get('test_gen_log_path'))
    save_logs(f'Total Test Rec True Counter {len(list(filter(lambda x : x==1, f1_rec_trues)))}',args.get('test_gen_log_path'))
    save_logs(f'Total Test Rec Pred Counter {len(list(filter(lambda x : x==1, f1_rec_preds)))}',args.get('test_gen_log_path'))
    save_logs(f'Total Counter {len(f1_rec_preds)}',args.get('test_gen_log_path'))
    save_logs(f'First Hello Count : {hellocnt}',args.get('test_gen_log_path'))

    tokenized = [line.split() for line in lines]
    for n in range(1, 6):
        cnt, percent = distinct_n_grams(tokenized, n)
        dist.append(percent)
        print(f'Distinct {n}-grams (cnt, percentage) = ({cnt}, {percent:.3f})')
    
    return Bleu, f1, dist


def evaluate_gen_gorecdial(test_loader:DataLoader, model:ProRec, graph_data, bow_data, args, golden_intent=True):
    pass


# HJ CONV_SAVE
def save_conv(path,hist,gen,label,gpt_in):
    with open(path, 'a', encoding='utf-8') as f:
        f.write("<< Context >>\n")
        for i in hist:
            f.write(f'{i}\n')
        f.write(f'Real_Resp: {label}\n')
        f.write(f'Generated: {gen}\n')
        f.write(f'GPT_input: {gpt_in}\n')
        f.write("\n================< NEW LINE >================\n\n")
