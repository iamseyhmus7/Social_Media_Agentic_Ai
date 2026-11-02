import * as Dialog from '@radix-ui/react-dialog';
import type {ButtonHTMLAttributes, ComponentProps, ReactNode} from 'react';
import {X} from 'lucide-react';
import {clsx, type ClassValue} from 'clsx';
import {twMerge} from 'tailwind-merge';
// Local shadcn-style primitives: Radix accessibility, owned source and CSS tokens.
export function cn(...inputs:ClassValue[]){return twMerge(clsx(inputs));}
export function Button({className,variant='primary',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'ghost'|'danger'}){return <button className={cn('button','button-'+variant,className)} {...props}/>;}
// Owned Card composition following shadcn/ui's Card/Header/Content pattern.
export function Card({className,...props}:ComponentProps<'div'>){return <div data-slot="card" className={cn('ui-card',className)} {...props}/>;}
export function CardHeader({className,...props}:ComponentProps<'div'>){return <div data-slot="card-header" className={cn('ui-card-header',className)} {...props}/>;}
export function CardTitle({className,...props}:ComponentProps<'h3'>){return <h3 data-slot="card-title" className={cn('ui-card-title',className)} {...props}/>;}
export function CardDescription({className,...props}:ComponentProps<'p'>){return <p data-slot="card-description" className={cn('ui-card-description',className)} {...props}/>;}
export function CardContent({className,...props}:ComponentProps<'div'>){return <div data-slot="card-content" className={cn('ui-card-content',className)} {...props}/>;}
export function Modal({open,onClose,title,description,children,wide=false}:{open:boolean;onClose:()=>void;title:string;description?:string;children:ReactNode;wide?:boolean}){
return <Dialog.Root open={open} onOpenChange={value=>!value&&onClose()}><Dialog.Portal><Dialog.Overlay className="modal-backdrop"/><Dialog.Content className={cn('modal',wide&&'modal-wide')}><Dialog.Title className="modal-title">{title}</Dialog.Title><Dialog.Description className="modal-description">{description||'Değişiklikleri inceleyip işlemi tamamla.'}</Dialog.Description><Dialog.Close className="icon-button modal-close" aria-label="Kapat"><X size={18}/></Dialog.Close>{children}</Dialog.Content></Dialog.Portal></Dialog.Root>;
}
